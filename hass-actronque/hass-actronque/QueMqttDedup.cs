using System;
using System.Collections.Concurrent;
using System.Globalization;

namespace HMX.HASSActronQue
{
    // Small helper for de-duplicating MQTT state publishes, with numeric tolerance for floating values.
    // - If payloads are numeric (parseable as double) they are compared numerically using a tolerance (default 0.1).
    // - Non-numeric payloads are compared as exact strings.
    // - Callers can pass a custom numericTolerance (in the same units as the numeric payload); pass null to use default (0.1).
    internal static class QueMqttDedup
    {
        // topic -> last published entry
        private class LastEntry
        {
            public string Payload;
            public double? Numeric;
        }

        private static readonly ConcurrentDictionary<string, LastEntry> _lastPublished = new ConcurrentDictionary<string, LastEntry>(StringComparer.Ordinal);

        // Default numeric tolerance used when payloads are numeric and no explicit tolerance supplied.
        private const double DefaultNumericTolerance = 0.1;

        // Publish only if payload changed (with optional numeric tolerance).
        // If numericTolerance == null and payloads parse as numbers, DefaultNumericTolerance is used.
        public static void PublishStateIfChanged(string topic, string payload, double? numericTolerance = null)
        {
            if (topic == null) return;
            if (payload == null) payload = "";

            // Try parse payload as invariant double
            if (!double.TryParse(payload, NumberStyles.Float | NumberStyles.AllowThousands, CultureInfo.InvariantCulture, out double parsedValue))
                parsedValue = double.NaN;

            bool isNumeric = !double.IsNaN(parsedValue);

            // Fast path: try update existing entry
            if (_lastPublished.TryGetValue(topic, out LastEntry existing))
            {
                if (isNumeric && existing.Numeric.HasValue)
                {
                    double tol = numericTolerance ?? DefaultNumericTolerance;
                    if (Math.Abs(existing.Numeric.Value - parsedValue) <= tol)
                        return; // within tolerance -> skip publish

                    var newEntry = new LastEntry { Payload = payload, Numeric = parsedValue };
                    if (_lastPublished.TryUpdate(topic, newEntry, existing))
                    {
                        MQTT.SendMessage(topic, payload);
                    }
                    else
                    {
                        // race with concurrent update; retry once
                        PublishStateIfChanged(topic, payload, numericTolerance);
                    }
                }
                else
                {
                    // String comparison fallback
                    if (string.Equals(existing.Payload, payload, StringComparison.Ordinal))
                        return; // identical -> skip

                    var newEntry = new LastEntry { Payload = payload, Numeric = isNumeric ? (double?)parsedValue : null };
                    if (_lastPublished.TryUpdate(topic, newEntry, existing))
                    {
                        MQTT.SendMessage(topic, payload);
                    }
                    else
                    {
                        PublishStateIfChanged(topic, payload, numericTolerance);
                    }
                }
            }
            else
            {
                // No previous entry, try add
                var addEntry = new LastEntry { Payload = payload, Numeric = isNumeric ? (double?)parsedValue : null };
                if (_lastPublished.TryAdd(topic, addEntry))
                {
                    MQTT.SendMessage(topic, payload);
                }
                else
                {
                    // race with concurrent add; retry once
                    PublishStateIfChanged(topic, payload, numericTolerance);
                }
            }
        }

        // Clear all cached topics for a unit so subsequent publishes will be sent (useful on registration or when forcing re-publish).
        public static void ClearLastPublishedForUnit(string unitSerial)
        {
            if (string.IsNullOrEmpty(unitSerial)) return;

            string prefix = $"actronque{unitSerial}/";
            foreach (var key in _lastPublished.Keys)
            {
                if (key.StartsWith(prefix, StringComparison.Ordinal))
                {
                    _lastPublished.TryRemove(key, out _);
                }
            }
        }

        // Clear a single topic explicitly
        public static void ClearTopic(string topic)
        {
            if (string.IsNullOrEmpty(topic)) return;
            _lastPublished.TryRemove(topic, out _);
        }
    }
}