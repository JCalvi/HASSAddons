﻿using System;
using System.Globalization;

namespace HMX.HASSActronQue
{
    class Program
    {
		static void Main(string[] strArgs)
        {
			CultureInfo.DefaultThreadCurrentCulture = new CultureInfo("en-AU");
			CultureInfo.DefaultThreadCurrentUICulture = new CultureInfo("en-AU");

			Service.Start();
		}
	}
}
