use home_weather_core::forecast::build_result;
use serde_json::Value;

#[test]
fn python_reference_complete_responses() {
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/forecast_cases.json")).unwrap();
    for (index, case) in cases.iter().enumerate() {
        let result = build_result(
            case["location"].clone(),
            case["data"].clone(),
            serde_json::from_value(case["warnings"].clone()).unwrap(),
            case["target"].as_str().unwrap(),
            case["include_hourly"].as_bool().unwrap(),
            case["language"].as_str().unwrap(),
            Some(
                chrono::DateTime::parse_from_rfc3339(case["now"].as_str().unwrap())
                    .unwrap()
                    .with_timezone(&chrono::Utc),
            ),
        )
        .unwrap();
        assert_eq!(result, case["expected"], "Python parity case {index}");
    }
}
#[test]
fn invalid_dates_missing_values_and_current_errors() {
    use serde_json::json;
    let location = json!({"timezone":"Asia/Tokyo"});
    let now = Some("2026-09-05T00:00:00Z".parse().unwrap());
    assert!(build_result(
        location.clone(),
        json!({}),
        vec![],
        "today",
        false,
        "en",
        now
    )
    .is_err());
    assert!(build_result(
        location.clone(),
        json!({"daily":{"time":["2026-09-05"]}}),
        vec![],
        "today",
        false,
        "en",
        now
    )
    .is_err());
    assert!(build_result(
        location.clone(),
        json!({"current":{"time":"2026-09-05T09:00"}}),
        vec![],
        "current",
        false,
        "en",
        now
    )
    .is_err());
    assert!(build_result(location, json!({}), vec![], "yesterday", false, "en", now).is_err());
}

#[test]
fn python_temperature_rounding_and_thresholds() {
    let cases: Vec<Value> =
        serde_json::from_str(include_str!("fixtures/temperature.json")).unwrap();
    for case in cases {
        assert_eq!(
            home_weather_core::forecast::temperature(&case[0], &case[1]).unwrap(),
            case[2]
        );
    }
}
#[test]
fn existing_unicode_casefold_mappings() {
    let cases: Vec<[String; 2]> =
        serde_json::from_str(include_str!("fixtures/casefold.json")).unwrap();
    for [original, expected] in cases {
        assert_eq!(
            home_weather_core::locations::fold(&original),
            expected,
            "{original:?}"
        );
    }
}

#[test]
fn oversized_integer_temperatures_are_rejected_before_rounding() {
    use serde_json::json;
    for (high, low) in [
        (9007199254740993i64, 9007199254740992i64),
        (9007199254740992, -1),
    ] {
        let error =
            home_weather_core::forecast::temperature(&json!(high), &json!(low)).unwrap_err();
        assert!(error.to_string().contains("binary64"));
        let result = build_result(
            json!({"timezone":"Asia/Tokyo"}),
            json!({"daily":{"time":["2026-09-05"],"temperature_2m_max":[high],"temperature_2m_min":[low]}}),
            vec![],
            "today",
            false,
            "en",
            Some("2026-09-05T00:00:00Z".parse().unwrap()),
        );
        assert!(result.unwrap_err().to_string().contains("binary64"));
    }
    assert_eq!(
        home_weather_core::forecast::temperature(
            &json!(9007199254740992i64),
            &json!(9007199254740991i64)
        )
        .unwrap()["value_c"],
        1.0
    );
}
