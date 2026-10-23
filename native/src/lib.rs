//! Pure weather calculations. No allocation across the ABI, I/O, or TLS.

#[no_mangle]
pub extern "C" fn weather_core_abi() -> u32 {
    1
}

#[no_mangle]
pub extern "C" fn weather_temperature_range(high: f64, low: f64) -> f64 {
    if !high.is_finite() || !low.is_finite() || high < low {
        return f64::NAN;
    }
    let delta = high - low;
    if !delta.is_finite() {
        return f64::NAN;
    }
    // Decimal formatting rounds the binary float to nearest, ties to even.
    format!("{delta:.10}").parse().unwrap_or(f64::NAN)
}

#[no_mangle]
pub extern "C" fn weather_is_large(delta: f64) -> i32 {
    if !delta.is_finite() {
        -1
    } else {
        i32::from(delta >= 7.0)
    }
}

#[no_mangle]
pub extern "C" fn weather_rain_code(code: f64) -> i32 {
    i32::from(
        [
            51., 53., 55., 56., 57., 61., 63., 65., 66., 67., 80., 81., 82., 95., 96., 99.,
        ]
        .contains(&code),
    )
}

/// Mask bits indicate original numeric values, distinguishing missing from NaN.
#[no_mangle]
pub extern "C" fn weather_rain_likely(
    code: f64,
    probability: f64,
    rain: f64,
    showers: f64,
    mask: u32,
) -> i32 {
    if mask & 15 == 0 {
        return -1;
    }
    i32::from(
        (mask & 1 != 0 && weather_rain_code(code) == 1)
            || (mask & 2 != 0 && probability >= 50.)
            || (mask & 4 != 0 && rain > 0.)
            || (mask & 8 != 0 && showers > 0.),
    )
}

#[no_mangle]
pub extern "C" fn weather_heat_category(high: f64) -> u32 {
    if high <= 10. {
        0
    } else if high <= 18. {
        1
    } else if high <= 26. {
        2
    } else if high <= 29. {
        3
    } else {
        4
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn range_edges() {
        assert_eq!(weather_temperature_range(27.1, 20.1), 7.);
        assert_eq!(weather_is_large(7.), 1);
        assert_eq!(weather_is_large(6.999999), 0);
        for (hi, lo) in [
            (0., 1.),
            (f64::NAN, 0.),
            (f64::INFINITY, 0.),
            (f64::MAX, -f64::MAX),
        ] {
            assert!(weather_temperature_range(hi, lo).is_nan());
        }
    }
    #[test]
    fn rain_unknown_and_thresholds() {
        assert_eq!(weather_rain_likely(61., 100., 1., 1., 0), -1);
        assert_eq!(weather_rain_likely(61., 0., 0., 0., 1), 1);
        assert_eq!(weather_rain_likely(0., 50., 0., 0., 2), 1);
        assert_eq!(weather_rain_likely(0., 49., 0., 0., 2), 0);
        assert_eq!(weather_rain_code(61.5), 0);
    }
}

pub mod api;
pub mod config_path;
pub mod forecast;
mod labels;
pub mod locations;
pub mod server;
