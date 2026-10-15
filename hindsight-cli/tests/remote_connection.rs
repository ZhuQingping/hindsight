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

    fn run(&self, args: &[&str]) -> Output {
        Command::new(env!("CARGO_BIN_EXE_agentstratum"))
            .env("HOME", &self.0)
            .env_remove("AGENTSTRATUM_API_URL")
            .env_remove("AGENTSTRATUM_API_KEY")
            .env_remove("AGENTSTRATUM_PROFILE")
            .args(args)
            .output()
            .unwrap()
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
