// q_rng.cs - the inspirational rng for a q channel (the .cs flavor)
// One line out = one value in. Declare:  qN|q_rng.exe  (built by build_q_rng.cmd)
using System;
using System.Globalization;

class q_rng
{
    static void Main()
    {
        var r = new Random();
        Console.WriteLine((r.NextDouble() * 100.0).ToString("F2", CultureInfo.InvariantCulture));
    }
}
