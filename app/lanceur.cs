// Lanceur de Bureau des Traders.exe : démarre app\server.py avec le Python du bureau, sans fenêtre noire.
// Compiler : app\compiler-exe.bat
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

static class Lanceur
{
    [STAThread]
    static void Main()
    {
        string dossier = AppDomain.CurrentDomain.BaseDirectory;
        string python = Path.Combine(dossier, @"app\.venv\Scripts\pythonw.exe");
        string serveur = Path.Combine(dossier, @"app\server.py");
        if (!File.Exists(python) || !File.Exists(serveur))
        {
            MessageBox.Show("Python du bureau introuvable :\n" + python +
                "\n\nRecrée-le avec :\nuv venv app\\.venv --python 3.12\nuv pip install --python app\\.venv\\Scripts\\python.exe pywebview",
                "Bureau des Traders", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        var info = new ProcessStartInfo(python, "\"" + serveur + "\"");
        info.WorkingDirectory = dossier;
        info.UseShellExecute = false;
        Process.Start(info);
    }
}
