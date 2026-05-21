import React, { useState } from "react";
import { useStore } from "../store";
import { exportFlow, previewExport } from "../api";
import { Download, Eye, FileCode, Terminal } from "lucide-react";

export default function ExportPanel() {
  const { activeFlow } = useStore();
  const [format, setFormat] = useState<"bash" | "python" | "both">("both");
  const [outputDir, setOutputDir] = useState("./results");
  const [preview, setPreview] = useState<{ path: string; content: string }[] | null>(null);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!activeFlow) {
    return <div className="p-4 text-sm text-gray-400">Select a flow to export.</div>;
  }

  async function doPreview() {
    if (!activeFlow) return;
    setLoading(true);
    try {
      const files = await previewExport(activeFlow, format, outputDir);
      setPreview(files);
      setSelectedFile(files[0]?.path ?? null);
    } catch (e) {
      alert("Preview failed: " + String(e));
    } finally {
      setLoading(false);
    }
  }

  async function doExport() {
    if (!activeFlow) return;
    setLoading(true);
    try {
      await exportFlow(activeFlow, format, outputDir);
    } catch (e) {
      alert("Export failed: " + String(e));
    } finally {
      setLoading(false);
    }
  }

  const selectedContent = preview?.find((f) => f.path === selectedFile)?.content ?? "";

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 bg-gray-50">
        <p className="text-sm font-semibold text-gray-700">Export Scripts</p>
        <p className="text-xs text-gray-400 mt-0.5">
          Generate standalone scripts + .fio job files
        </p>
      </div>

      <div className="p-3 space-y-3 border-b border-gray-100">
        <div>
          <p className="text-xs text-gray-500 mb-1.5">Format</p>
          <div className="flex gap-2">
            {(["bash", "python", "both"] as const).map((f) => (
              <button key={f}
                onClick={() => setFormat(f)}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border ${
                  format === f
                    ? "bg-blue-600 text-white border-blue-600"
                    : "bg-white text-gray-600 border-gray-200 hover:border-blue-300"
                }`}>
                {f === "bash" && <Terminal size={11} />}
                {f === "python" && <FileCode size={11} />}
                {f === "both" && <Download size={11} />}
                {f}
              </button>
            ))}
          </div>
        </div>

        <label className="flex flex-col gap-0.5">
          <span className="text-xs text-gray-500">Results output dir (in generated scripts)</span>
          <input value={outputDir} onChange={(e) => setOutputDir(e.target.value)}
            className="text-xs border border-gray-200 rounded px-2 py-1.5 font-mono focus:outline-none focus:ring-1 focus:ring-blue-400"
            placeholder="./results" />
        </label>

        <div className="flex gap-2">
          <button onClick={doPreview} disabled={loading}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-medium disabled:opacity-40">
            <Eye size={12} /> Preview
          </button>
          <button onClick={doExport} disabled={loading}
            className="flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold disabled:opacity-40">
            <Download size={12} /> Download ZIP
          </button>
        </div>
      </div>

      {/* File preview */}
      {preview && (
        <div className="flex-1 overflow-hidden flex flex-col">
          <div className="flex gap-0 overflow-x-auto border-b border-gray-100">
            {preview.map((f) => (
              <button key={f.path}
                onClick={() => setSelectedFile(f.path)}
                className={`px-3 py-1.5 text-xs whitespace-nowrap border-r border-gray-100 ${
                  selectedFile === f.path
                    ? "bg-white text-blue-700 font-semibold"
                    : "bg-gray-50 text-gray-500 hover:text-gray-700"
                }`}>
                {f.path}
              </button>
            ))}
          </div>
          <pre className="flex-1 overflow-auto bg-gray-950 text-gray-100 text-xs font-mono p-4 leading-5">
            {selectedContent}
          </pre>
        </div>
      )}
    </div>
  );
}
