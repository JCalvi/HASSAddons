using System;

namespace HMX.HASSActronQue
{
	public partial class Que
	{
		[Flags]
		public enum UpdateItems
		{
			None = 0,
			Main = 1,
			Zone1 = 2,
			Zone2 = 4,
			Zone3 = 8,
			Zone4 = 16,
			Zone5 = 32,
			Zone6 = 64,
			Zone7 = 128,
			Zone8 = 256
		}

		public enum TemperatureSetType
		{
			Default,
			High,
			Low
		}
	}
}