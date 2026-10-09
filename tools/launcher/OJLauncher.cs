// ============================================================================
//  OJ 一键启动器（WinForms，单文件，编译产物为真正的 .exe）
//
//  双击后：启动判题机 → 启动后端中控台 → 自动打开浏览器访问中控台。
//  也支持命令行（便于自动化/排错，结果写入 logs\launcher.log）：
//      OJ中控台.exe --start [--no-browser]   启动并退出（不开界面）
//      OJ中控台.exe --stop                   全部停止
//      OJ中控台.exe --status                 写状态后退出（0=都在跑，1=有没跑的）
//
//  编译：tools\build_launcher.cmd（用系统自带 csc.exe，不需要装任何东西）
// ============================================================================
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Windows.Forms;

static class OjEnv
{
    public static string Root;
    public static string Python;
    public static string LogFile;
    public static int ConsolePort = 8090;
    public static string ConsoleUrl { get { return "http://127.0.0.1:" + ConsolePort + "/"; } }
    public static string FrontUrl = "https://yhsome.github.io/oj-ojojoj/";

    static OjEnv()
    {
        // 1) 仓库根目录：exe 所在目录优先；找不到就回退到 D:\OJ
        string dir = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        if (File.Exists(Path.Combine(dir, "tools", "oj_service.py"))) Root = dir;
        else if (File.Exists(@"D:\OJ\tools\oj_service.py")) Root = @"D:\OJ";
        else Root = dir;

        // 2) Python：先用随 DSH 附带的运行时，其次 PATH 里的 python
        string bundled = @"C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe";
        if (File.Exists(bundled)) Python = bundled; else Python = "python";

        LogFile = Path.Combine(Root, "logs", "launcher.log");
        try { Directory.CreateDirectory(Path.Combine(Root, "logs")); } catch { }
    }

    public static void Log(string msg)
    {
        string line = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") + "  " + msg;
        try { File.AppendAllText(LogFile, line + Environment.NewLine, Encoding.UTF8); } catch { }
        if (OnLog != null) OnLog(line);
    }

    public static Action<string> OnLog;

    public static bool PortOpen(int port, int timeoutMs)
    {
        try
        {
            using (var c = new TcpClient())
            {
                var ar = c.BeginConnect("127.0.0.1", port, null, null);
                if (!ar.AsyncWaitHandle.WaitOne(timeoutMs)) return false;
                c.EndConnect(ar);
                return true;
            }
        }
        catch { return false; }
    }

    /// <summary>跑一个 python 脚本并等它结束（隐藏窗口），返回输出。</summary>
    public static string RunPython(string scriptArgs, int timeoutMs)
    {
        var psi = new ProcessStartInfo();
        psi.FileName = Python;
        psi.Arguments = scriptArgs;
        psi.WorkingDirectory = Root;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.RedirectStandardOutput = true;
        psi.RedirectStandardError = true;
        psi.StandardOutputEncoding = Encoding.UTF8;
        psi.StandardErrorEncoding = Encoding.UTF8;
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        try
        {
            var p = Process.Start(psi);
            string outp = p.StandardOutput.ReadToEnd() + p.StandardError.ReadToEnd();
            if (!p.WaitForExit(timeoutMs)) { try { p.Kill(); } catch { } return outp + "\n(超时)"; }
            return outp;
        }
        catch (Exception e) { return "启动失败: " + e.Message; }
    }

    /// <summary>后台常驻启动（中控台服务用），不等待退出。</summary>
    public static Process StartDetached(string scriptArgs)
    {
        var psi = new ProcessStartInfo();
        psi.FileName = Python;
        psi.Arguments = scriptArgs;
        psi.WorkingDirectory = Root;
        psi.UseShellExecute = false;
        psi.CreateNoWindow = true;
        psi.RedirectStandardOutput = false;
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        return Process.Start(psi);
    }

    public static int JudgePid()
    {
        try
        {
            string lockPath = Path.Combine(Root, "data", "state", "daemon.lock");
            if (!File.Exists(lockPath)) return 0;
            string txt = File.ReadAllText(lockPath, Encoding.UTF8);
            var m = Regex.Match(txt, "\"pid\"\\s*:\\s*(\\d+)");
            if (!m.Success) return 0;
            int pid = int.Parse(m.Groups[1].Value);
            try { var p = Process.GetProcessById(pid); return p.HasExited ? 0 : pid; }
            catch { return 0; }
        }
        catch { return 0; }
    }

    public static bool JudgeRunning() { return JudgePid() > 0; }

    public static void OpenUrl(string url)
    {
        try { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); }
        catch (Exception e) { Log("打开浏览器失败: " + e.Message); }
    }

    /// <summary>启动中控台服务（若端口未监听），返回是否可用。</summary>
    public static bool EnsureConsole()
    {
        if (PortOpen(ConsolePort, 400)) { Log("中控台已在运行（:" + ConsolePort + "）"); return true; }
        Log("启动中控台服务 python tools/console.py --port " + ConsolePort + " …");
        StartDetached("tools\\console.py --port " + ConsolePort);
        for (int i = 0; i < 60; i++)
        {
            Thread.Sleep(300);
            if (PortOpen(ConsolePort, 300)) { Log("中控台已就绪: " + ConsoleUrl); return true; }
        }
        Log("中控台启动超时（20 秒内端口未监听）");
        return false;
    }

    public static bool StartJudge()
    {
        if (JudgeRunning()) { Log("判题机已在运行（pid=" + JudgePid() + "）"); return true; }
        Log("启动判题机 …");
        string outp = RunPython("tools\\oj_service.py start", 90000);
        foreach (string line in outp.Split('\n'))
            if (line.Trim().Length > 0) Log("  | " + line.TrimEnd());
        return JudgeRunning();
    }

    public static bool StopAll()
    {
        bool ok = true;
        Log("停止判题机 …");
        RunPython("tools\\oj_service.py stop", 60000);
        ok = !JudgeRunning();
        // 中控台：按端口找 pid 结束
        int pid = PidByPort(ConsolePort);
        if (pid > 0)
        {
            Log("停止中控台（pid=" + pid + "）");
            try { Process.GetProcessById(pid).Kill(); } catch { }
            Thread.Sleep(600);
        }
        if (PortOpen(ConsolePort, 300)) { Log("中控台仍在监听，请手动检查"); ok = false; }
        return ok;
    }

    public static int PidByPort(int port)
    {
        try
        {
            var psi = new ProcessStartInfo("netstat", "-ano -p tcp");
            psi.UseShellExecute = false; psi.CreateNoWindow = true;
            psi.RedirectStandardOutput = true; psi.StandardOutputEncoding = Encoding.ASCII;
            var p = Process.Start(psi);
            string txt = p.StandardOutput.ReadToEnd();
            p.WaitForExit(10000);
            foreach (string line in txt.Split('\n'))
            {
                if (line.IndexOf(":" + port, StringComparison.Ordinal) < 0) continue;
                if (line.IndexOf("LISTENING", StringComparison.OrdinalIgnoreCase) < 0) continue;
                var parts = line.Split(new char[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
                if (parts.Length >= 5)
                {
                    int pid;
                    if (int.TryParse(parts[parts.Length - 1], out pid)) return pid;
                }
            }
            return 0;
        }
        catch { return 0; }
    }
}

class MainForm : Form
{
    Label lJudge, lConsole, lHint;
    TextBox box;
    Button bStart, bStop, bConsole, bFront;
    System.Windows.Forms.Timer timer;

    public MainForm()
    {
        Text = "OJ 判题机 · 后端中控台";
        ClientSize = new Size(560, 400);
        StartPosition = FormStartPosition.CenterScreen;
        Font = new Font("Microsoft YaHei UI", 9F);

        var title = new Label();
        title.Text = "一键启动：判题机 + 中控台";
        title.Font = new Font(Font.FontFamily, 13F, FontStyle.Bold);
        title.AutoSize = true; title.Location = new Point(16, 14);
        Controls.Add(title);

        lJudge = new Label(); lJudge.AutoSize = true; lJudge.Location = new Point(18, 52);
        lConsole = new Label(); lConsole.AutoSize = true; lConsole.Location = new Point(18, 76);
        lHint = new Label(); lHint.AutoSize = true; lHint.Location = new Point(18, 100);
        lHint.ForeColor = Color.DimGray;
        lHint.Text = "提示：中控台里可以调参数、看日志、暂停/恢复判题。";
        Controls.Add(lJudge); Controls.Add(lConsole); Controls.Add(lHint);

        bStart = new Button(); bStart.Text = "▶  一键启动"; bStart.Location = new Point(18, 130);
        bStart.Size = new Size(126, 36); bStart.Click += (s, e) => DoStart(true);
        bStop = new Button(); bStop.Text = "■  全部停止"; bStop.Location = new Point(152, 130);
        bStop.Size = new Size(126, 36); bStop.Click += (s, e) => DoStop();
        bConsole = new Button(); bConsole.Text = "打开中控台"; bConsole.Location = new Point(286, 130);
        bConsole.Size = new Size(120, 36);
        bConsole.Click += (s, e) => { OjEnv.EnsureConsole(); OjEnv.OpenUrl(OjEnv.ConsoleUrl); };
        bFront = new Button(); bFront.Text = "打开考生前端"; bFront.Location = new Point(414, 130);
        bFront.Size = new Size(128, 36);
        bFront.Click += (s, e) => OjEnv.OpenUrl(OjEnv.FrontUrl);
        Controls.Add(bStart); Controls.Add(bStop); Controls.Add(bConsole); Controls.Add(bFront);

        box = new TextBox();
        box.Multiline = true; box.ScrollBars = ScrollBars.Vertical;
        box.Location = new Point(18, 178); box.Size = new Size(524, 204);
        box.ReadOnly = true; box.BackColor = Color.FromArgb(20, 22, 28);
        box.ForeColor = Color.Gainsboro; box.Font = new Font("Consolas", 9F);
        Controls.Add(box);

        OjEnv.OnLog = (line) =>
        {
            if (box.IsDisposed) return;
            try
            {
                box.AppendText(line + "\r\n");
                box.SelectionStart = box.TextLength; box.ScrollToCaret();
            }
            catch { }
        };

        timer = new System.Windows.Forms.Timer(); timer.Interval = 2000;
        timer.Tick += (s, e) => Refresh2();
        timer.Start();

        Load += (s, e) =>
        {
            Refresh2();
            if (OjEnv.JudgeRunning() && OjEnv.PortOpen(OjEnv.ConsolePort, 300))
                OjEnv.Log("已经在运行中：直接点「打开中控台」即可");
            else
                DoStart(true);   // 双击即一键启动
        };
    }

    void Refresh2()
    {
        bool j = OjEnv.JudgeRunning(), c = OjEnv.PortOpen(OjEnv.ConsolePort, 250);
        int pid = OjEnv.JudgePid();
        lJudge.Text = "判题机：" + (j ? "运行中（pid=" + pid + "）" : "已停止");
        lJudge.ForeColor = j ? Color.SeaGreen : Color.Firebrick;
        lConsole.Text = "中控台：" + (c ? "运行中  " + OjEnv.ConsoleUrl : "已停止");
        lConsole.ForeColor = c ? Color.SeaGreen : Color.Firebrick;
    }

    void DoStart(bool openBrowser)
    {
        bStart.Enabled = false;
        ThreadPool.QueueUserWorkItem(_ =>
        {
            try
            {
                OjEnv.StartJudge();
                bool cok = OjEnv.EnsureConsole();
                if (cok && openBrowser)
                {
                    OjEnv.Log("打开浏览器 " + OjEnv.ConsoleUrl);
                    OjEnv.OpenUrl(OjEnv.ConsoleUrl);
                }
            }
            finally
            {
                try { BeginInvoke(new Action(() => { bStart.Enabled = true; Refresh2(); })); }
                catch { }
            }
        });
    }

    void DoStop()
    {
        bStop.Enabled = false;
        ThreadPool.QueueUserWorkItem(_ =>
        {
            try { OjEnv.StopAll(); }
            finally
            {
                try { BeginInvoke(new Action(() => { bStop.Enabled = true; Refresh2(); })); }
                catch { }
            }
        });
    }
}

static class Program
{
    [STAThread]
    static int Main(string[] args)
    {
        bool headless = false, noBrowser = false, doStop = false, doStatus = false;
        foreach (string a in args)
        {
            string s = a.ToLowerInvariant();
            if (s == "--start") headless = true;
            else if (s == "--no-browser") noBrowser = true;
            else if (s == "--stop") { headless = true; doStop = true; }
            else if (s == "--status") { headless = true; doStatus = true; }
        }

        if (headless)
        {
            OjEnv.Log("=== 命令行模式: " + string.Join(" ", args) + " ===");
            if (doStatus)
            {
                bool j = OjEnv.JudgeRunning(), c = OjEnv.PortOpen(OjEnv.ConsolePort, 300);
                OjEnv.Log("判题机: " + (j ? "运行中 pid=" + OjEnv.JudgePid() : "已停止"));
                OjEnv.Log("中控台: " + (c ? "运行中 " + OjEnv.ConsoleUrl : "已停止"));
                return (j && c) ? 0 : 1;
            }
            if (doStop) return OjEnv.StopAll() ? 0 : 1;
            bool okJ = OjEnv.StartJudge();
            bool okC = OjEnv.EnsureConsole();
            if (okC && !noBrowser) OjEnv.OpenUrl(OjEnv.ConsoleUrl);
            OjEnv.Log("结果: 判题机=" + (okJ ? "OK" : "失败") + " 中控台=" + (okC ? "OK" : "失败"));
            return (okJ && okC) ? 0 : 1;
        }

        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new MainForm());
        return 0;
    }
}
