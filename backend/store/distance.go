package store

import "math"

// Drive time is estimated from great-circle distance: real roads wiggle, so
// multiply by a factor, then assume an average mixed-driving speed. Accurate
// to roughly ±15 minutes which is fine for "what's within an hour".
const (
	RoadWiggleFactor = 1.2
	AverageSpeedKmh  = 60.0
)

const earthRadiusKm = 6371.0

// HaversineKm returns the great-circle distance in km between two points.
func HaversineKm(lat1, lon1, lat2, lon2 float64) float64 {

	toRad := func(d float64) float64 { return d * math.Pi / 180 }
	dLat := toRad(lat2 - lat1)
	dLon := toRad(lon2 - lon1)
	a := math.Sin(dLat/2)*math.Sin(dLat/2) +
		math.Cos(toRad(lat1))*math.Cos(toRad(lat2))*math.Sin(dLon/2)*math.Sin(dLon/2)
	return 2 * earthRadiusKm * math.Asin(math.Sqrt(a))
}

// DriveMinutes estimates driving time for a crow-flies distance.
func DriveMinutes(crowFliesKm float64) float64 {
	return crowFliesKm * RoadWiggleFactor / AverageSpeedKmh * 60
}
