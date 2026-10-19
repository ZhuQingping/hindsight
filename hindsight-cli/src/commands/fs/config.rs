//! Configuration resolution for the `fs` subcommand.
//!
//! Priority (highest first): explicit CLI flags > saved mount config
//! (`<dir>/.contextbase-fs/config.json`) > the CLI's resolved API endpoint
//! (profile/env/config file) > `fs`-specific defaults.
//!
//! The saved config is written when a folder is first mounted so that later
//! commands run against that folder (status/stop/sync) reuse the same bank and
//! endpoint without re-passing flags — and so the detached daemon can rehydrate
//! its target after re-exec.

use anyhow::{bail, Result};
use serde::{Deserialize, Serialize};
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use super::paths::CONTROL_DIR;

pub const DEFAULT_INTERVAL_SECONDS: u64 = 30;
pub const DEFAULT_DIR: &str = "./contextbase-fs";

/// Effective configuration for a mount.
#[derive(Debug, Clone)]
pub struct MountConfig {
    /// Absolute path to the mount directory.
    pub dir: PathBuf,
    /// ContextBase API base URL (no trailing slash).
    pub api_url: String,
    /// Bearer token, if the API requires auth.
    pub api_token: Option<String>,
    /// Bank whose knowledge base is mirrored.
    pub bank_id: String,
    /// Refresh interval in seconds for the sync loop.
    pub interval_seconds: u64,
    /// When false (the default), mirrored files are written read-only so agents
    /// cannot edit them. Set true to opt into editable files (still one-way).
    pub writable: bool,
}

/// Overrides supplied directly on the command line (all optional).
#[derive(Debug, Default, Clone)]
pub struct ConfigOverrides {
    pub dir: Option<String>,
    pub api_url: Option<String>,
    pub api_token: Option<String>,
    pub bank_id: Option<String>,
    pub interval_seconds: Option<u64>,
    /// Only `true` overrides — an unset flag leaves the saved/default value.
    pub writable: bool,
}

/// Optional CLI endpoint (empty when absent), below explicit flags and saved
/// mount config. Only the final effective endpoint is validated.
#[derive(Debug, Clone)]
pub struct Baseline {
    pub api_url: String,
    pub api_key: Option<String>,
}

/// Partial config persisted alongside a mount.
#[derive(Debug, Default, Serialize, Deserialize)]
struct SavedConfig {
    #[serde(skip_serializing_if = "Option::is_none", default)]
    api_url: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    api_token: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    bank_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none", default)]
    interval_seconds: Option<u64>,
    #[serde(default)]
    writable: bool,
}

fn strip_trailing_slash(url: &str) -> String {
    url.trim().trim_end_matches('/').to_string()
}

fn control_dir(dir: &Path) -> PathBuf {
    dir.join(CONTROL_DIR)
}

fn read_saved_config(dir: &Path) -> SavedConfig {
    let file = control_dir(dir).join("config.json");
    fs::read_to_string(file)
        .ok()
        .and_then(|raw| serde_json::from_str(&raw).ok())
        .unwrap_or_default()
}

/// Resolve the effective config for a command.
///
/// Remote commands require a valid endpoint and bank after merging all sources.
/// Local commands can inspect or remove a mount without either being configured.
pub fn resolve_config(
    overrides: &ConfigOverrides,
    baseline: &Baseline,
    require_remote: bool,
) -> Result<MountConfig> {
    let dir_input = overrides
        .dir
        .clone()
        .or_else(|| env::var("CONTEXTBASE_FS_DIR").ok())
        .unwrap_or_else(|| DEFAULT_DIR.to_string());
    // Absolutize against the current dir without requiring the path to exist.
    let dir = {
        let p = PathBuf::from(&dir_input);
        if p.is_absolute() {
            p
        } else {
            env::current_dir().map(|cwd| cwd.join(&p)).unwrap_or(p)
        }
    };

    let saved = read_saved_config(&dir);

    let api_url = strip_trailing_slash(
        overrides
            .api_url
            .as_deref()
            .or(saved.api_url.as_deref())
            .unwrap_or(&baseline.api_url),
    );

    // A token saved for another endpoint must not follow an explicit URL
    // override. A standalone environment token is an explicit user setting.
    let api_token = overrides
        .api_token
        .clone()
        .or_else(|| {
            saved.api_token.filter(|_| {
                saved
                    .api_url
                    .as_deref()
                    .map(strip_trailing_slash)
                    .as_deref()
                    == Some(api_url.as_str())
            })
        })
        .or_else(|| {
            if baseline.api_url.is_empty() || strip_trailing_slash(&baseline.api_url) == api_url {
                baseline.api_key.clone()
            } else {
                None
            }
        });

    if require_remote {
        crate::config::Config::validate_and_create(
            api_url.clone(),
            None,
            crate::config::ConfigSource::LocalFile,
        )?;
    }

    let bank_id = overrides
        .bank_id
        .clone()
        .or(saved.bank_id)
        .or_else(|| env::var("CONTEXTBASE_BANK_ID").ok())
        .unwrap_or_default();

    if require_remote && bank_id.is_empty() {
        bail!(
            "No bank specified. Pass --bank <id>, set CONTEXTBASE_BANK_ID, or run inside an already-mounted folder."
        );
    }

    let interval_seconds = overrides
        .interval_seconds
        .or(saved.interval_seconds)
        .or_else(|| {
            env::var("CONTEXTBASE_FS_INTERVAL")
                .ok()
                .and_then(|s| s.parse::<u64>().ok())
        })
        .filter(|&n| n >= 1)
        .unwrap_or(DEFAULT_INTERVAL_SECONDS);

    let writable = overrides.writable || saved.writable;

    Ok(MountConfig {
        dir,
        api_url,
        api_token,
        bank_id,
        interval_seconds,
        writable,
    })
}

/// Persist the parts of a config worth remembering for a mounted folder.
pub fn save_config(config: &MountConfig) -> Result<()> {
    let cdir = control_dir(&config.dir);
    fs::create_dir_all(&cdir)?;
    let saved = SavedConfig {
        api_url: Some(config.api_url.clone()),
        api_token: config.api_token.clone(),
        bank_id: Some(config.bank_id.clone()),
        interval_seconds: Some(config.interval_seconds),
        writable: config.writable,
    };
    let mut body = serde_json::to_string_pretty(&saved)?;
    body.push('\n');
    fs::write(cdir.join("config.json"), body)?;
    Ok(())
}
