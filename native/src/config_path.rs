//! Match the previous expanduser().resolve() path behavior for ordinary home paths.
use anyhow::{ensure, Context, Result};
use std::{
    env, fs,
    path::{Component, Path, PathBuf},
};

pub fn resolve(path: &Path) -> Result<PathBuf> {
    let path = if path.starts_with("~") {
        PathBuf::from(env::var_os("HOME").context("HOME is unavailable.")?)
            .join(path.strip_prefix("~")?)
    } else {
        path.to_path_buf()
    };
    let absolute = if path.is_absolute() {
        path
    } else {
        env::current_dir()?.join(path)
    };
    resolve_absolute(&absolute, 0)
}
fn resolve_absolute(path: &Path, depth: usize) -> Result<PathBuf> {
    ensure!(depth < 40, "Too many symbolic links in configuration path.");
    let mut resolved = PathBuf::new();
    for component in path.components() {
        match component {
            Component::RootDir => resolved.push(Path::new("/")),
            Component::CurDir => {}
            Component::ParentDir => {
                resolved.pop();
            }
            Component::Normal(name) => {
                resolved.push(name);
                match fs::symlink_metadata(&resolved) {
                    Ok(meta) if meta.file_type().is_symlink() => {
                        let link = fs::read_link(&resolved)?;
                        let target = if link.is_absolute() {
                            link
                        } else {
                            resolved
                                .parent()
                                .context("Invalid link parent.")?
                                .join(link)
                        };
                        resolved = resolve_absolute(&target, depth + 1)?;
                    }
                    Ok(_) => {}
                    Err(e) if e.kind() == std::io::ErrorKind::NotFound => {}
                    Err(e) => return Err(e.into()),
                }
            }
            Component::Prefix(_) => anyhow::bail!("Unsupported configuration path prefix."),
        }
    }
    Ok(resolved)
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn resolves_existing_and_dangling_links_without_replacing_them() -> Result<()> {
        let dir = tempfile::tempdir()?;
        fs::create_dir(dir.path().join("real"))?;
        std::os::unix::fs::symlink("real", dir.path().join("link"))?;
        std::os::unix::fs::symlink("real/locations.json", dir.path().join("config"))?;
        let expected = fs::canonicalize(dir.path().join("real"))?.join("locations.json");
        assert_eq!(resolve(&dir.path().join("link/locations.json"))?, expected);
        assert_eq!(resolve(&dir.path().join("config"))?, expected);
        assert!(dir
            .path()
            .join("config")
            .symlink_metadata()?
            .file_type()
            .is_symlink());
        Ok(())
    }
}
