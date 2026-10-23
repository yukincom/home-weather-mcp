//! Version-1 settings, Unicode aliases, and process-safe atomic updates.
use anyhow::{bail, ensure, Context, Result};
use fs2::FileExt;
use serde_json::{json, Value};
use std::{
    collections::HashSet,
    fs::{self, File, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
};

use unicode_normalization::UnicodeNormalization;

pub fn clean_name(value: &str) -> Result<String> {
    let normalized: String = value.nfkc().collect();
    let name =
        normalized.trim_matches(|c: char| c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c));
    ensure!(
        !name.is_empty() && name.chars().count() <= 120 && !name.chars().any(|c| c < ' '),
        "Names must contain 1 to 120 characters."
    );
    Ok(name.to_owned())
}
pub fn fold(name: &str) -> String {
    caseless::default_case_fold_str(name)
}
fn names(row: &Value) -> Vec<&str> {
    let mut result = vec![row["alias"].as_str().unwrap_or("")];
    if let Some(aliases) = row["additional_aliases"].as_array() {
        result.extend(aliases.iter().filter_map(Value::as_str));
    }
    result
}
pub fn validate_location(mut row: Value) -> Result<Value> {
    ensure!(row.is_object(), "Location must be an object.");
    for key in ["alias", "place_name"] {
        row[key] = json!(clean_name(
            row[key]
                .as_str()
                .context("Location names must be strings.")?
        )?);
    }
    let aliases = match row.get("additional_aliases") {
        None => Vec::new(),
        Some(value) => value
            .as_array()
            .context("additional_aliases must be a list.")?
            .iter()
            .map(|v| clean_name(v.as_str().context("Aliases must be strings.")?))
            .collect::<Result<Vec<_>>>()?,
    };
    row["additional_aliases"] = json!(aliases);
    let all_names = names(&row);
    ensure!(
        all_names.len() <= 10
            && all_names
                .iter()
                .map(|n| fold(n))
                .collect::<HashSet<_>>()
                .len()
                == all_names.len(),
        "Use at most 10 unique names per location."
    );
    if let Some(default) = row.get("is_default") {
        ensure!(default.is_boolean(), "is_default must be a boolean.");
    }
    for (key, limit) in [("latitude", 90.0), ("longitude", 180.0)] {
        let number = row[key]
            .as_f64()
            .context(format!("{key} is out of range."))?;
        ensure!(
            number.is_finite() && number.abs() <= limit,
            "{key} is out of range."
        );
    }
    row["timezone"]
        .as_str()
        .context("timezone must be a string.")?
        .parse::<chrono_tz::Tz>()
        .context("Unknown timezone.")?;
    Ok(row)
}
fn validate_rows(rows: &[Value]) -> Result<()> {
    let aliases: Vec<_> = rows.iter().flat_map(names).map(fold).collect();
    ensure!(
        rows.len() <= 3 && aliases.iter().collect::<HashSet<_>>().len() == aliases.len(),
        "Use at most 3 locations with unique names."
    );
    ensure!(
        rows.is_empty() || rows.iter().filter(|row| row["is_default"] == true).count() == 1,
        "Exactly one default location is required."
    );
    Ok(())
}
fn find(rows: &[Value], alias: Option<&str>) -> Result<Value> {
    if let Some(alias) = alias {
        let alias = clean_name(alias)?;
        if let Some(row) = rows
            .iter()
            .find(|r| names(r).iter().any(|n| fold(n) == fold(&alias)))
        {
            return Ok(row.clone());
        }
        bail!("Unknown location: {alias}. Use weather_list_locations to check names.");
    }
    rows.iter()
        .find(|row| row["is_default"] == true)
        .cloned()
        .context("No locations registered. Use weather_set_location to add one.")
}
#[derive(Clone)]
pub struct LocationStore {
    pub path: PathBuf,
}
impl LocationStore {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self { path: path.into() }
    }
    pub fn list(&self) -> Result<Vec<Value>> {
        let bytes = match fs::read(&self.path) {
            Ok(bytes) => bytes,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                return Ok(vec![
                    json!({"alias":"Tokyo","additional_aliases":["東京"],"place_name":"Tokyo, Japan","latitude":35.6895,"longitude":139.69171,"timezone":"Asia/Tokyo","is_default":true}),
                ])
            }
            Err(error) => return Err(error.into()),
        };
        let data: Value =
            serde_json::from_slice(&bytes).context("Invalid location configuration JSON.")?;
        ensure!(
            data["version"] == 1,
            "Invalid location configuration format."
        );
        let rows = data["locations"]
            .as_array()
            .context("Invalid location configuration format.")?
            .iter()
            .cloned()
            .map(validate_location)
            .collect::<Result<Vec<_>>>()?;
        validate_rows(&rows)?;
        Ok(rows)
    }
    pub fn get(&self, alias: Option<&str>) -> Result<Value> {
        find(&self.list()?, alias)
    }
    fn modify(&self, operation: impl FnOnce(&mut Vec<Value>) -> Result<Value>) -> Result<Value> {
        let parent = self
            .path
            .parent()
            .filter(|p| !p.as_os_str().is_empty())
            .unwrap_or(Path::new("."));
        fs::create_dir_all(parent)?;
        let mut lock_path = self.path.as_os_str().to_os_string();
        lock_path.push(".lock");
        let lock = OpenOptions::new()
            .create(true)
            .append(true)
            .open(PathBuf::from(lock_path))?;
        lock.lock_exclusive()?;
        let mut rows = self.list()?;
        let result = operation(&mut rows)?;
        validate_rows(&rows)?;
        let mut temporary = tempfile::Builder::new()
            .prefix(".locations-")
            .tempfile_in(parent)?;
        serde_json::to_writer_pretty(&mut temporary, &json!({"version":1,"locations":rows}))?;
        temporary.write_all(b"\n")?;
        temporary.as_file().sync_all()?;
        temporary.persist(&self.path).map_err(|e| e.error)?;
        File::open(parent)?.sync_all()?;
        Ok(result) // Dropping lock releases the advisory lock on success or failure.
    }
    pub fn set(&self, item: Value) -> Result<Value> {
        let mut item = validate_location(item)?;
        self.modify(|rows| {
            ensure!(
                !rows
                    .iter()
                    .any(|r| fold(r["alias"].as_str().unwrap())
                        == fold(item["alias"].as_str().unwrap())),
                "Name already registered. Use weather_update_location to change it."
            );
            ensure!(
                rows.len() < 3,
                "At most 3 locations are allowed. Update or remove an existing location."
            );
            item["is_default"] = json!(rows.is_empty() || item["is_default"] == true);
            if item["is_default"] == true {
                for row in rows.iter_mut() {
                    row["is_default"] = json!(false);
                }
            }
            rows.push(item.clone());
            Ok(item)
        })
    }
    pub fn update(&self, alias: &str, updates: Value) -> Result<Value> {
        self.modify(|rows| {
            let old = find(rows, Some(alias))?;
            let index = rows
                .iter()
                .position(|r| r["alias"] == old["alias"])
                .context("Location disappeared.")?;
            let mut item = old;
            item.as_object_mut().unwrap().extend(
                updates
                    .as_object()
                    .context("Updates must be an object.")?
                    .clone(),
            );
            item = validate_location(item)?;
            if updates["is_default"] == true {
                for row in rows.iter_mut() {
                    row["is_default"] = json!(false);
                }
            }
            rows[index] = item.clone();
            Ok(item)
        })
    }
    pub fn remove(&self, alias: &str) -> Result<Value> {
        self.modify(|rows| {
            let old = find(rows, Some(alias))?;
            rows.retain(|r| r["alias"] != old["alias"]);
            if old["is_default"] == true && !rows.is_empty() {
                rows[0]["is_default"] = json!(true);
            }
            Ok(old)
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn place(alias: &str) -> Value {
        json!({"alias":alias,"place_name":"Osaka, Japan","latitude":34.7,"longitude":135.5,"timezone":"Asia/Tokyo"})
    }
    #[test]
    fn unicode_defaults_update_and_empty_persist() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let store = LocationStore::new(dir.path().join("locations.json"));
        assert_eq!(store.get(Some("Ｔｏｋｙｏ"))?["alias"], "Tokyo");
        assert!(!store.path.exists());
        store.set(place("Straße"))?;
        assert_eq!(store.get(Some("STRASSE"))?["alias"], "Straße");
        store.update(
            "strasse",
            json!({"alias":"Office","additional_aliases":["職場"],"is_default":true}),
        )?;
        assert_eq!(store.get(None)?["alias"], "Office");
        store.remove("職場")?;
        store.remove("東京")?;
        assert!(store.list()?.is_empty());
        assert!(store.get(None).is_err());
        Ok(())
    }
    #[test]
    fn invalid_changes_leave_file_intact() -> Result<()> {
        let dir = tempfile::tempdir()?;
        let store = LocationStore::new(dir.path().join("locations.json"));
        store.set(place("Office"))?;
        let before = fs::read(&store.path)?;
        assert!(store
            .update("Office", json!({"additional_aliases":["東京"]}))
            .is_err());
        assert_eq!(before, fs::read(&store.path)?);
        store.set(place("Travel"))?;
        assert!(store.set(place("Fourth")).is_err());
        let mut invalid = place("Bad");
        invalid["latitude"] = json!(true);
        assert!(validate_location(invalid).is_err());
        fs::write(&store.path, "{bad json")?;
        assert!(store.set(place("Bad")).is_err());
        assert_eq!(fs::read_to_string(&store.path)?, "{bad json");
        Ok(())
    }
}
