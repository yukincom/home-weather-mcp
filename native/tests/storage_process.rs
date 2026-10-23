use home_weather_core::locations::LocationStore;
use serde_json::json;
use std::process::Command;

// Each subprocess contends on the same real flock rather than a thread mutex.
#[test]
fn writer_child() {
    if let Ok(path) = std::env::var("WEATHER_STORAGE_TEST_PATH") {
        let index = std::env::var("WEATHER_STORAGE_TEST_INDEX").unwrap();
        let store = LocationStore::new(path);
        let _=store.set(json!({"alias":format!("Place{index}"),"place_name":"Osaka","latitude":34.7,"longitude":135.5,"timezone":"Asia/Tokyo"}));
    }
}
#[test]
fn concurrent_process_writes_never_lose_updates_or_exceed_limit() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("locations.json");
    let executable = std::env::current_exe().unwrap();
    let mut children = Vec::new();
    for index in 0..8 {
        children.push(
            Command::new(&executable)
                .args(["--exact", "writer_child"])
                .env("WEATHER_STORAGE_TEST_PATH", &path)
                .env("WEATHER_STORAGE_TEST_INDEX", index.to_string())
                .stdout(std::process::Stdio::null())
                .spawn()
                .unwrap(),
        );
    }
    for mut child in children {
        assert!(child.wait().unwrap().success());
    }
    let rows = LocationStore::new(&path).list().unwrap();
    assert_eq!(rows.len(), 3);
    assert_eq!(rows.iter().filter(|r| r["is_default"] == true).count(), 1);
    assert_eq!(std::fs::read_dir(dir.path()).unwrap().count(), 2); // settings + lock, no orphan temp files
}
