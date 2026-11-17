//! #337: the compiler is its own package. Nothing in this directory may name the project it was
//! first built for, or reach outside the directory: no host module path, no host package name, no
//! path that climbs out. A host's names come in through `--config` (`src/host.rs`); a host's
//! tests live with the host. Documentation (`*.md`) is exempt: it may tell the history.
//!
//! Red on any file (code, runtime, fixtures, manifests) that names one, with every offence listed.

use std::path::{Path, PathBuf};

/// Spelled in pieces so this file does not trip its own scan.
fn forbidden() -> Vec<String> {
    [
        ["bant", "am"].concat(),
        ["runtime", "-ts"].concat(),
        ["runtime", "-py"].concat(),
        ["_gene", "rated"].concat(),
        ["tools/", "ts2py"].concat(),
        ["\"../", ".."].concat(),
        ["join(\"", "..\")"].concat(),
    ]
    .into_iter()
    .collect()
}

fn files(dir: &Path, out: &mut Vec<PathBuf>) {
    let mut entries: Vec<_> = std::fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .collect();
    entries.sort();
    for path in entries {
        let name = path.file_name().unwrap().to_string_lossy().to_string();
        if path.is_dir() {
            if name != "target" && name != "__pycache__" && !name.starts_with('.') {
                files(&path, out);
            }
        } else if !name.ends_with(".md") {
            out.push(path);
        }
    }
}

#[test]
fn the_package_names_no_host_and_reaches_nothing_outside_itself() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let mut all = Vec::new();
    files(root, &mut all);
    assert!(
        all.iter().any(|p| p.ends_with("src/lower.rs")),
        "the scan must see the compiler"
    );
    let words = forbidden();
    let mut offences = Vec::new();
    for path in &all {
        let Ok(text) = std::fs::read_to_string(path) else {
            continue;
        };
        let shown = path.strip_prefix(root).unwrap().display().to_string();
        for (n, line) in text.lines().enumerate() {
            let lower = line.to_lowercase();
            for word in &words {
                if lower.contains(word.as_str()) {
                    offences.push(format!("{shown}:{}: {word}: {}", n + 1, line.trim()));
                }
            }
        }
    }
    assert!(
        offences.is_empty(),
        "{} offence(s) against the package boundary (#337):\n{}",
        offences.len(),
        offences.join("\n")
    );
}
