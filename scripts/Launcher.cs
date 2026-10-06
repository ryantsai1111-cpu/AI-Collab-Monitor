using System;
using System.IO;
using System.Diagnostics;
using System.Reflection;
using System.Text.RegularExpressions;
using System.Windows.Forms;

[assembly: AssemblyTitle("AI Collaboration Workspace")]
[assembly: AssemblyProduct("AI Collaboration Workspace")]
[assembly: AssemblyVersion("1.0.0.0")]
[assembly: AssemblyFileVersion("1.0.0.0")]
[assembly: AssemblyInformationalVersion("1.0.0-candidate; executable acceptance pending")]

class Launcher {
  // These exact .NET regex constants are exercised by the offline argv oracle.
  internal const string QuotePattern = @"(\\*)""";
  internal const string QuoteReplacement = @"$1$1\""";
  internal const string TrailingPattern = @"(\\+)\z";
  internal const string TrailingReplacement = @"$1$1";
  internal static string QuoteArgument(string argument) {
    string escaped = Regex.Replace(argument, QuotePattern, QuoteReplacement);
    return "\"" + Regex.Replace(escaped, TrailingPattern, TrailingReplacement) + "\"";
  }
  internal static bool IsAbsolutePath(string path) {
    // Path.IsPathRooted alone also accepts C:relative and root-relative paths.
    if (String.IsNullOrEmpty(path)) return false;
    return (path.Length >= 3 && Char.IsLetter(path[0]) && path[1] == ':' &&
            (path[2] == '\\' || path[2] == '/')) || path.StartsWith("\\\\");
  }
  [STAThread] static int Main(string[] args) {
    try {
      string data = null;
      if (args.Length != 0) {
        if (args.Length != 2 || args[0] != "--data-dir" || !IsAbsolutePath(args[1])) {
          MessageBox.Show("Usage: AI Collaboration Workspace.exe [--data-dir <absolute path>]\nInvalid arguments: Python was not started.", "AI Collaboration Workspace");
          return 2;
        }
        try { data = Path.GetFullPath(args[1]); }
        catch (Exception invalidPath) {
          MessageBox.Show("Invalid --data-dir: " + invalidPath.Message + ". Python was not started.", "AI Collaboration Workspace");
          return 2;
        }
      }
      string root = AppDomain.CurrentDomain.BaseDirectory;
      string config = Path.Combine(root, "python-path.txt");
      if (!File.Exists(config)) throw new IOException("Missing Python configuration: " + config);
      string python = File.ReadAllText(config).Trim().TrimStart('\uFEFF');
      if (!IsAbsolutePath(python)) throw new IOException("Configured Python must be an absolute path.");
      python = Path.GetFullPath(python);
      string name = Path.GetFileName(python);
      if (!name.Equals("pythonw.exe", StringComparison.OrdinalIgnoreCase) &&
          !name.Equals("python.exe", StringComparison.OrdinalIgnoreCase))
        throw new IOException("Configured runtime must be pythonw.exe or python.exe.");
      if (!File.Exists(python)) throw new IOException("Configured existing Python is missing: " + python);
      string script = Path.Combine(root, "run.py");
      if (!File.Exists(script)) throw new IOException("Missing application entry point: " + script);
      string arguments = QuoteArgument(script);
      if (data != null) arguments += " --data-dir " + QuoteArgument(data);
      using (Process child = Process.Start(new ProcessStartInfo(python, arguments) {
        WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true
      })) {
        if (child == null) throw new IOException("Python process was not created.");
        if (child.WaitForExit(2000) && child.ExitCode != 0) {
          MessageBox.Show("Python exited early with code " + child.ExitCode + ". No UI readiness is claimed.", "AI Collaboration Workspace");
          return 3;
        }
      }
      // 0 means process-start/early-exit check only, NOT UI readiness/EXE acceptance.
      return 0;
    } catch (Exception error) {
      MessageBox.Show(error.Message, "AI Collaboration Workspace");
      return 1;
    }
  }
}
