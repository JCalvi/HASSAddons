using Microsoft.AspNetCore.Mvc;
using System;
using System.Linq;

namespace HMX.HASSActronQue.Controllers
{
	[ApiController]
	[Route("[controller]")]
	public class HealthController : ControllerBase
	{
		[HttpGet]
		public IActionResult Get()
		{
			try
			{
				// Get MQTT health
				var (mqttConnected, lastMqttMessage, mqttSent, mqttFailed) = MQTT.GetHealth();

				// Get token status
				var tokenValid = false;
				DateTime? tokenExpiry = null;
				try
				{
					// Access token via reflection to avoid exposing it publicly
					var queType = typeof(Que);
					var tokenField = queType.GetField("_queToken", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static);
					if (tokenField != null)
					{
						var token = tokenField.GetValue(null) as QueToken;
						if (token != null)
						{
							tokenValid = token.TokenExpires > DateTime.UtcNow;
							tokenExpiry = token.TokenExpires;
						}
					}
				}
				catch
				{
					// Ignore reflection errors
				}

				// Get last API call time from units
				DateTime? lastApiCall = null;
				int unitCount = 0;
				try
				{
					var units = Que.Units;
					if (units != null)
					{
						unitCount = units.Count;
						var lastUpdated = units.Values
							.Where(u => u?.Data != null && u.Data.LastUpdated != DateTime.MinValue)
							.Select(u => u.Data.LastUpdated)
							.OrderByDescending(d => d)
							.FirstOrDefault();
						
						if (lastUpdated != DateTime.MinValue)
							lastApiCall = lastUpdated;
					}
				}
				catch
				{
					// Ignore errors
				}

				// Get queue depth (optional - requires exposing queue count)
				int queueDepth = 0;
				try
				{
					var queType = typeof(Que);
					var queueField = queType.GetField("_queueCommands", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static);
					if (queueField != null)
					{
						var queue = queueField.GetValue(null) as System.Collections.Queue;
						if (queue != null)
							queueDepth = queue.Count;
					}
				}
				catch
				{
					// Ignore reflection errors
				}

				var health = new
				{
					status = mqttConnected && tokenValid ? "healthy" : "degraded",
					timestamp = DateTime.UtcNow.ToString("o"),
					mqtt = new
					{
						connected = mqttConnected,
						lastMessage = lastMqttMessage == DateTime.MinValue ? null : lastMqttMessage.ToString("o"),
						messagesSent = mqttSent,
						messagesFailed = mqttFailed
					},
					token = new
					{
						valid = tokenValid,
						expires = tokenExpiry?.ToString("o")
					},
					api = new
					{
						lastCall = lastApiCall?.ToString("o"),
						unitCount = unitCount,
						queueDepth = queueDepth
					}
				};

				return Ok(health);
			}
			catch (Exception ex)
			{
				return StatusCode(500, new { error = ex.Message });
			}
		}
	}
}