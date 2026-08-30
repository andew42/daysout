package store

import (
	"math"
	"os"
	"regexp"
	"strconv"
	"testing"
)

func TestHaversineKnownDistance(t *testing.T) {

	// London (Charing Cross) to Bristol (city centre) is ~171 km great-circle.
	got := HaversineKm(51.5074, -0.1278, 51.4545, -2.5879)
	if math.Abs(got-171) > 3 {
		t.Errorf("London-Bristol haversine = %.1f km, want ~171 km", got)
	}
}

func TestHaversineZero(t *testing.T) {

	if got := HaversineKm(51.5, -1.5, 51.5, -1.5); got != 0 {
		t.Errorf("identical points = %f, want 0", got)
	}
}

func TestDriveMinutes(t *testing.T) {

	// 50 km crow-flies * 1.2 / 60 km/h = exactly one hour.
	got := DriveMinutes(60.0 / RoadWiggleFactor)
	if math.Abs(got-60) > 0.01 {
		t.Errorf("DriveMinutes = %f, want 60", got)
	}
}

// The map draws its drive-time ring in the browser from its own copy of
// these constants, while every distance shown inside the ring is computed
// here. Changing one side alone draws a circle that disagrees with its own
// contents, and nothing else would catch it.
func TestTheFrontendUsesTheSameConstants(t *testing.T) {

	source, err := os.ReadFile("../../frontend/src/MapView.jsx")
	if err != nil {
		t.Skipf("frontend not present: %v", err)
	}

	for _, c := range []struct{ name, want string }{
		{"ROAD_WIGGLE_FACTOR", strconv.FormatFloat(RoadWiggleFactor, 'g', -1, 64)},
		{"AVERAGE_SPEED_KMH", strconv.FormatFloat(AverageSpeedKmh, 'g', -1, 64)},
	} {
		pattern := regexp.MustCompile(`const ` + c.name + ` = ([0-9.]+)`)
		match := pattern.FindSubmatch(source)
		if match == nil {
			t.Errorf("MapView.jsx no longer declares %s — keep it in step with this file",
				c.name)
			continue
		}
		if got := string(match[1]); got != c.want {
			t.Errorf("MapView.jsx %s = %s, but store has %s", c.name, got, c.want)
		}
	}
}
