package store

import (
	"math"
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

	// 46.15 km crow-flies * 1.3 / 60 km/h = exactly one hour.
	got := DriveMinutes(60.0 / RoadWiggleFactor)
	if math.Abs(got-60) > 0.01 {
		t.Errorf("DriveMinutes = %f, want 60", got)
	}
}
