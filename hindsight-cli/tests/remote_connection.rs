use std::fs;
use std::path::PathBuf;
use std::process::{Command, Output};
use std::time::{SystemTime, UNIX_EPOCH};

struct TestHome(PathBuf);

impl TestHome {
    fn new() -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path =
            std::env::temp_dir().join(format!("agentstratum-cli-{}-{}", std::process::id(), nonce));
        fs::create_dir_all(&path).unwrap();
        Self(path)
    }

    fn command(&self, args: &[&str]) -> Command {
        let mut command = Command::new(env!("CARGO_BIN_EXE_agentstratum"));
        command
            .env("HOME", &self.0)
            .env_remove("AGENTSTRATUM_API_URL")
            .env_remove("AGENTSTRATUM_API_KEY")
            .env_remove("AGENTSTRATUM_PROFILE")
            .env_remove("AGENTSTRATUM_FS_DIR")
            .env_remove("AGENTSTRATUM_BANK_ID")
            .env_remove("AGENTSTRATUM_FS_INTERVAL")
            .env_remove("HTTP_PROXY")
            .env_remove("HTTPS_PROXY")
            .env_remove("ALL_PROXY")
            .env_remove("http_proxy")
            .env_remove("https_proxy")
            .env_remove("all_proxy")
            .env("no_proxy", "*")
            .env("NO_PROXY", "*")
            .current_dir(&self.0)
            .args(args);
        command
    }

    fn run(&self, args: &[&str]) -> Output {
        self.command(args).output().unwrap()
    }
}

impl Drop for TestHome {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn unconfigured_cli_explains_endpoint_and_has_no_ui_installer() {
    let home = TestHome::new();
    let output = home.run(&["bank", "list"]);
    assert!(!output.status.success());
    assert!(String::from_utf8_lossy(&output.stderr).contains("API Endpoint is required"));
    assert!(!home.run(&["ui"]).status.success());
}

#[test]
fn changing_endpoint_drops_existing_credential() {
    let home = TestHome::new();
    assert!(home
        .run(&[
            "configure",
            "--api-url",
            "https://first.example",
            "--api-key",
            "first-key"
        ])
        .status
        .success());
    assert!(home
        .run(&["configure", "--api-url", "https://second.example"])
        .status
        .success());
    let config = fs::read_to_string(home.0.join(".agentstratum/config")).unwrap();
    assert!(config.contains("https://second.example"));
    assert!(!config.contains("first-key"));
}

#[test]
fn profiles_keep_independent_endpoints() {
    let home = TestHome::new();
    for (profile, endpoint) in [
        ("first", "https://first.example"),
        ("second", "https://second.example"),
    ] {
        assert!(home
            .run(&["profile", "create", profile, "--api-url", endpoint])
            .status
            .success());
        let output = home.run(&["profile", "show", profile]);
        assert!(output.status.success());
        assert!(String::from_utf8_lossy(&output.stdout).contains(endpoint));
    }
}

struct TestServer {
    url: String,
    stop: std::sync::mpsc::Sender<()>,
    worker: Option<std::thread::JoinHandle<Vec<String>>>,
}

impl TestServer {
    fn new() -> Self {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let url = format!("http://{}", listener.local_addr().unwrap());
        let (stop, stopped) = std::sync::mpsc::channel();
        let worker = std::thread::spawn(move || {
            let mut requests = Vec::new();
            while stopped.try_recv().is_err() {
                match listener.accept() {
                    Ok((mut stream, _)) => {
                        stream
                            .set_read_timeout(Some(std::time::Duration::from_secs(3)))
                            .unwrap();
                        let mut request = Vec::new();
                        let mut buf = [0; 1024];
                        while !request.windows(4).any(|w| w == b"\r\n\r\n") {
                            let n = stream.read(&mut buf).unwrap();
                            assert!(n > 0);
                            request.extend_from_slice(&buf[..n]);
                        }
                        requests.push(String::from_utf8(request).unwrap());
                        stream.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}").unwrap();
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                        std::thread::sleep(std::time::Duration::from_millis(5));
                    }
                    Err(e) => panic!("{e}"),
                }
            }
            requests
        });
        Self {
            url,
            stop,
            worker: Some(worker),
        }
    }

    fn requests(mut self) -> Vec<String> {
        self.stop.send(()).unwrap();
        self.worker.take().unwrap().join().unwrap()
    }
}

impl Drop for TestServer {
    fn drop(&mut self) {
        let _ = self.stop.send(());
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

fn assert_fs_requests(requests: &[String], token: Option<&str>) {
    assert_eq!(requests.len(), 2);
    assert!(requests[0].starts_with("GET /v1/default/banks/review/knowledge-base/tree "));
    assert!(requests[1].starts_with("GET /v1/default/banks/review/knowledge-base/export "));
    for request in requests {
        let auth = request
            .lines()
            .find(|line| line.to_lowercase().starts_with("authorization:"));
        assert_eq!(
            auth.map(str::trim),
            token
                .map(|t| format!("authorization: Bearer {t}"))
                .as_deref()
        );
    }
}

#[test]
fn fs_explicit_endpoint_works_without_global_configuration() {
    let home = TestHome::new();
    let server = TestServer::new();
    let result = home.run(&[
        "fs",
        "list",
        "--api-url",
        &server.url,
        "--bank",
        "review",
        "--token",
        "explicit-key",
    ]);
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert_fs_requests(&server.requests(), Some("explicit-key"));
}

#[test]
fn fs_mount_then_sync_reuses_saved_connection_without_global_configuration() {
    let home = TestHome::new();
    let server = TestServer::new();
    let dir = home.0.join("mirror");
    let dir = dir.to_str().unwrap();
    let result = home.run(&[
        "fs",
        "mount",
        dir,
        "--once",
        "--api-url",
        &server.url,
        "--bank",
        "review",
        "--token",
        "saved-key",
    ]);
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    let result = home.run(&["fs", "sync", dir]);
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    let requests = server.requests();
    assert_eq!(requests.len(), 4);
    assert_fs_requests(&requests[..2], Some("saved-key"));
    assert_fs_requests(&requests[2..], Some("saved-key"));
}

#[test]
fn fs_uses_selected_profile_as_fallback() {
    let home = TestHome::new();
    let server = TestServer::new();
    assert!(home
        .run(&[
            "profile",
            "create",
            "test",
            "--api-url",
            &server.url,
            "--api-key",
            "profile-key"
        ])
        .status
        .success());
    let result = home.run(&["--profile", "test", "fs", "list", "--bank", "review"]);
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert_fs_requests(&server.requests(), Some("profile-key"));
}

#[test]
fn fs_endpoint_override_does_not_send_other_endpoints_credentials() {
    for saved in [false, true] {
        let home = TestHome::new();
        let server = TestServer::new();
        assert!(home
            .run(&[
                "configure",
                "--api-url",
                "https://other.example",
                "--api-key",
                "other-global-key"
            ])
            .status
            .success());
        let dir = home.0.join("mirror");
        if saved {
            let control = dir.join(".agentstratum-fs");
            fs::create_dir_all(&control).unwrap();
            fs::write(control.join("config.json"), r#"{"api_url":"https://saved.example","api_token":"other-saved-key","bank_id":"review"}"#).unwrap();
        }
        let result = home.run(&[
            "fs",
            "list",
            dir.to_str().unwrap(),
            "--api-url",
            &server.url,
            "--bank",
            "review",
        ]);
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        assert_fs_requests(&server.requests(), None);
    }
}

#[test]
fn fs_local_commands_do_not_require_endpoint_or_profile() {
    let home = TestHome::new();
    let dir = home.0.join("mirror");
    for cmd in ["logs", "stop", "status", "unmount"] {
        let result = home.run(&["--profile", "missing", "fs", cmd, dir.to_str().unwrap()]);
        let stderr = String::from_utf8_lossy(&result.stderr);
        assert!(!stderr.contains("API Endpoint"), "{stderr}");
        assert!(!stderr.contains("profile 'missing'"), "{stderr}");
        if cmd != "status" {
            assert!(result.status.success(), "{stderr}");
        } else {
            // An unmounted folder is unhealthy, but its status is still shown.
            assert!(String::from_utf8_lossy(&result.stdout).contains("Mount:"));
        }
    }
}

#[test]
fn fs_remote_commands_validate_effective_endpoint_before_writing_mount() {
    let home = TestHome::new();
    let dir = home.0.join("mirror");
    for url in [
        None,
        Some("file:///tmp/test"),
        Some("https://user:secret@example.com"),
    ] {
        let mut args = vec![
            "fs",
            "mount",
            dir.to_str().unwrap(),
            "--once",
            "--bank",
            "review",
        ];
        if let Some(url) = url {
            args.extend(["--api-url", url]);
        }
        let result = home.run(&args);
        assert!(!result.status.success());
        assert!(
            String::from_utf8_lossy(&result.stderr).contains(if url.is_none() {
                "API Endpoint is required"
            } else {
                "Invalid API URL"
            })
        );
        assert!(!dir.exists());
    }
}

#[test]
fn fs_environment_endpoint_and_standalone_token_are_supported() {
    for endpoint_in_env in [false, true] {
        let home = TestHome::new();
        let server = TestServer::new();
        let mut args = vec!["fs", "list", "--bank", "review"];
        if !endpoint_in_env {
            args.extend(["--api-url", &server.url]);
        }
        let mut command = home.command(&args);
        command.env("AGENTSTRATUM_API_KEY", "env-key");
        if endpoint_in_env {
            command.env("AGENTSTRATUM_API_URL", &server.url);
        }
        let result = command.output().unwrap();
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        assert_fs_requests(&server.requests(), Some("env-key"));
    }
}

#[test]
fn fs_validates_only_the_effective_url_and_keeps_profile_errors() {
    let home = TestHome::new();
    let server = TestServer::new();
    let result = home
        .command(&["fs", "list", "--bank", "review", "--api-url", &server.url])
        .env("AGENTSTRATUM_API_URL", "not-a-url")
        .env("AGENTSTRATUM_API_KEY", "unused-key")
        .output()
        .unwrap();
    assert!(
        result.status.success(),
        "{}",
        String::from_utf8_lossy(&result.stderr)
    );
    assert_fs_requests(&server.requests(), None);
    let result = home.run(&["--profile", "missing", "fs", "list", "--bank", "review"]);
    assert!(!result.status.success());
    assert!(String::from_utf8_lossy(&result.stderr).contains("profile 'missing' not found"));
    // Other CLI commands still require their configured endpoint to be valid.
    let result = home
        .command(&["health"])
        .env("AGENTSTRATUM_API_URL", "not-a-url")
        .output()
        .unwrap();
    assert!(!result.status.success());
    assert!(String::from_utf8_lossy(&result.stderr).contains("Invalid API URL"));
}

#[test]
fn fs_saved_endpoint_precedes_profile_and_same_endpoint_credentials_are_reused() {
    for saved_endpoint in [false, true] {
        let home = TestHome::new();
        let server = TestServer::new();
        let profile_url = if saved_endpoint {
            "https://other.example"
        } else {
            &server.url
        };
        assert!(home
            .run(&[
                "profile",
                "create",
                "test",
                "--api-url",
                profile_url,
                "--api-key",
                "profile-key"
            ])
            .status
            .success());
        let dir = home.0.join("mirror");
        let control = dir.join(".agentstratum-fs");
        fs::create_dir_all(&control).unwrap();
        fs::write(
            control.join("config.json"),
            serde_json::json!({
                "api_url": if saved_endpoint { &server.url } else { "https://saved.example" },
                "api_token": "saved-key", "bank_id": "review"
            })
            .to_string(),
        )
        .unwrap();
        let mut args = vec!["--profile", "test", "fs", "list", dir.to_str().unwrap()];
        if !saved_endpoint {
            args.extend(["--api-url", &server.url]);
        }
        let result = home.run(&args);
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        assert_fs_requests(
            &server.requests(),
            Some(if saved_endpoint {
                "saved-key"
            } else {
                "profile-key"
            }),
        );
    }
}
