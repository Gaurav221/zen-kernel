import React, { useCallback, useEffect, useRef } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  type NodeTypes,
  Handle,
  Position,
  Panel,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useStore } from "../store";
import type { FlowStep, StepType } from "../types";
import {
  Activity,
  Database,
  Terminal,
  Trash2,
  Settings,
  Plus,
  Zap,
} from "lucide-react";

// ─────────────────────────── Node colours ─────────────────────────────────

const NODE_STYLE: Record<StepType, { bg: string; border: string; icon: React.ReactNode }> = {
  fio: {
    bg: "bg-blue-50",
    border: "border-blue-400",
    icon: <Zap size={14} className="text-blue-600" />,
  },
  log_collect: {
    bg: "bg-emerald-50",
    border: "border-emerald-400",
    icon: <Activity size={14} className="text-emerald-600" />,
  },
  command: {
    bg: "bg-amber-50",
    border: "border-amber-400",
    icon: <Terminal size={14} className="text-amber-600" />,
  },
};

// ─────────────────────────── Custom node ──────────────────────────────────

function StepNode({ data, selected }: { data: FlowStep & { onDelete: () => void; onConfigure: () => void }; selected: boolean }) {
  const style = NODE_STYLE[data.type];
  return (
    <div
      className={`relative rounded-lg border-2 ${style.border} ${style.bg} shadow-sm min-w-[160px] max-w-[220px] ${selected ? "ring-2 ring-offset-1 ring-indigo-500" : ""}`}
    >
      <Handle type="target" position={Position.Left} className="!bg-gray-400" />

      <div className="px-3 py-2">
        <div className="flex items-center gap-1.5 mb-1">
          {style.icon}
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            {data.type.replace("_", " ")}
          </span>
        </div>
        <div className="text-sm font-medium text-gray-800 truncate">{data.name}</div>
        <div className="flex gap-1 mt-2">
          <button
            className="p-1 rounded hover:bg-white/70 text-gray-500 hover:text-indigo-600"
            title="Configure"
            onClick={(e) => { e.stopPropagation(); data.onConfigure(); }}
          >
            <Settings size={12} />
          </button>
          <button
            className="p-1 rounded hover:bg-white/70 text-gray-500 hover:text-red-600"
            title="Delete"
            onClick={(e) => { e.stopPropagation(); data.onDelete(); }}
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      <Handle type="source" position={Position.Right} className="!bg-gray-400" />
    </div>
  );
}

const nodeTypes: NodeTypes = { step: StepNode as any };

// ───────────────────────── FlowEditor component ───────────────────────────

export default function FlowEditor() {
  const { activeFlow, setActiveFlow, setSelectedStepId, setRightPanel } = useStore();

  const flowStepsToNodes = (steps: FlowStep[]): Node[] =>
    steps.map((step) => ({
      id: step.id,
      type: "step",
      position: { x: step.position_x || 0, y: step.position_y || 0 },
      data: {
        ...step,
        onDelete: () => deleteStep(step.id),
        onConfigure: () => {
          setSelectedStepId(step.id);
          setRightPanel(
            step.type === "fio"
              ? "fio-config"
              : step.type === "log_collect"
              ? "log-config"
              : "cmd-config",
          );
        },
      },
    }));

  const flowEdgesToEdges = (edges: FlowStep["id"][] | any[]): Edge[] =>
    (activeFlow?.edges ?? []).map((e: any) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      animated: false,
      style: { stroke: "#94a3b8" },
    }));

  const [nodes, setNodes, onNodesChange] = useNodesState(
    activeFlow ? flowStepsToNodes(activeFlow.steps) : [],
  );
  const [edges, setEdges, onEdgesChange] = useEdgesState(
    activeFlow ? flowEdgesToEdges(activeFlow.edges) : [],
  );

  // Sync when activeFlow changes from outside (e.g. loading a saved flow)
  useEffect(() => {
    if (!activeFlow) return;
    setNodes(flowStepsToNodes(activeFlow.steps));
    setEdges(flowEdgesToEdges(activeFlow.edges));
  }, [activeFlow?.id]);

  // Persist node positions back to flow
  const onNodeDragStop = useCallback(
    (_: any, node: Node) => {
      if (!activeFlow) return;
      const updated = {
        ...activeFlow,
        steps: activeFlow.steps.map((s) =>
          s.id === node.id
            ? { ...s, position_x: node.position.x, position_y: node.position.y }
            : s,
        ),
      };
      setActiveFlow(updated);
    },
    [activeFlow, setActiveFlow],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (!activeFlow) return;
      const newEdge: Edge = {
        id: `e-${connection.source}-${connection.target}`,
        source: connection.source!,
        target: connection.target!,
        style: { stroke: "#94a3b8" },
      };
      setEdges((eds) => addEdge(newEdge, eds));
      setActiveFlow({
        ...activeFlow,
        edges: [
          ...(activeFlow.edges ?? []),
          { id: newEdge.id, source: newEdge.source, target: newEdge.target },
        ],
      });
    },
    [activeFlow, setActiveFlow, setEdges],
  );

  const onEdgesDelete = useCallback(
    (deleted: Edge[]) => {
      if (!activeFlow) return;
      const ids = new Set(deleted.map((e) => e.id));
      setActiveFlow({
        ...activeFlow,
        edges: (activeFlow.edges ?? []).filter((e) => !ids.has(e.id)),
      });
    },
    [activeFlow, setActiveFlow],
  );

  const deleteStep = useCallback(
    (stepId: string) => {
      if (!activeFlow) return;
      setActiveFlow({
        ...activeFlow,
        steps: activeFlow.steps.filter((s) => s.id !== stepId),
        edges: (activeFlow.edges ?? []).filter(
          (e) => e.source !== stepId && e.target !== stepId,
        ),
      });
      setNodes((ns) => ns.filter((n) => n.id !== stepId));
      setEdges((es) =>
        es.filter((e) => e.source !== stepId && e.target !== stepId),
      );
    },
    [activeFlow, setActiveFlow, setNodes, setEdges],
  );

  const addStep = useCallback(
    (type: StepType) => {
      if (!activeFlow) return;
      const id = Math.random().toString(36).slice(2, 10);
      const existingCount = activeFlow.steps.filter((s) => s.type === type).length;
      const defaultName =
        type === "fio"
          ? `fio_test_${existingCount + 1}`
          : type === "log_collect"
          ? `log_collect_${existingCount + 1}`
          : `command_${existingCount + 1}`;

      const defaultConfig =
        type === "fio"
          ? {
              global_options: {
                ioengine: "libaio",
                direct: 1,
                group_reporting: 1,
                time_based: 1,
                runtime: 60,
                ramp_time: 5,
                numjobs: 1,
                thread: 1,
                log_avg_msec: 500,
              },
              jobs: [{ name: "job1", rw: "randread", bs: "4k", iodepth: 32 }],
            }
          : type === "log_collect"
          ? { collectors: [{ type: "dmesg", clear_before: false }], duration: null }
          : { command: "echo hello", label: "my_command", env: {}, fail_on_error: true };

      const xOffset = activeFlow.steps.length * 220;
      const newStep: FlowStep = {
        id,
        type,
        name: defaultName,
        config: defaultConfig as any,
        position_x: xOffset,
        position_y: 100,
      };

      const updated = { ...activeFlow, steps: [...activeFlow.steps, newStep] };
      setActiveFlow(updated);
      setNodes((ns) => [
        ...ns,
        {
          id,
          type: "step",
          position: { x: xOffset, y: 100 },
          data: {
            ...newStep,
            onDelete: () => deleteStep(id),
            onConfigure: () => {
              setSelectedStepId(id);
              setRightPanel(
                type === "fio" ? "fio-config" : type === "log_collect" ? "log-config" : "cmd-config",
              );
            },
          },
        },
      ]);
    },
    [activeFlow, setActiveFlow, setNodes, deleteStep, setSelectedStepId, setRightPanel],
  );

  const onNodeClick = useCallback(
    (_: any, node: Node) => {
      const step = activeFlow?.steps.find((s) => s.id === node.id);
      if (!step) return;
      setSelectedStepId(step.id);
      setRightPanel(
        step.type === "fio" ? "fio-config" : step.type === "log_collect" ? "log-config" : "cmd-config",
      );
    },
    [activeFlow, setSelectedStepId, setRightPanel],
  );

  if (!activeFlow) {
    return (
      <div className="flex-1 flex items-center justify-center bg-gray-50 text-gray-400">
        <div className="text-center">
          <Database size={48} className="mx-auto mb-3 opacity-40" />
          <p className="text-lg font-medium">No flow selected</p>
          <p className="text-sm mt-1">Create a new flow or open an existing one from the sidebar</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex-1 relative" style={{ height: "100%" }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onEdgesDelete={onEdgesDelete}
        onNodeDragStop={onNodeDragStop}
        onNodeClick={onNodeClick}
        nodeTypes={nodeTypes}
        fitView
        deleteKeyCode="Delete"
      >
        <Background color="#e2e8f0" gap={20} />
        <Controls />
        <MiniMap nodeColor={(n: Node) => {
          const step = activeFlow.steps.find((s) => s.id === n.id);
          return step?.type === "fio" ? "#93c5fd" : step?.type === "log_collect" ? "#6ee7b7" : "#fcd34d";
        }} />

        <Panel position="top-left">
          <div className="flex gap-2 bg-white rounded-lg shadow p-1.5 border border-gray-200">
            <button
              onClick={() => addStep("fio")}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-blue-50 hover:bg-blue-100 text-blue-700 text-xs font-medium border border-blue-200"
            >
              <Zap size={12} /> FIO Test
            </button>
            <button
              onClick={() => addStep("log_collect")}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-emerald-50 hover:bg-emerald-100 text-emerald-700 text-xs font-medium border border-emerald-200"
            >
              <Activity size={12} /> Log Collect
            </button>
            <button
              onClick={() => addStep("command")}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-amber-50 hover:bg-amber-100 text-amber-700 text-xs font-medium border border-amber-200"
            >
              <Terminal size={12} /> Command
            </button>
          </div>
        </Panel>

        <Panel position="top-right">
          <div className="bg-white/90 rounded-lg shadow px-3 py-1.5 border border-gray-200 text-xs text-gray-500 space-y-0.5">
            <div><span className="text-blue-600 font-bold">→</span> Drag from handle to connect steps</div>
            <div><span className="text-red-500 font-bold">Del</span> key or <span className="text-gray-700 font-medium">⚙</span> to remove</div>
            <div>Parallel steps = same source node</div>
          </div>
        </Panel>
      </ReactFlow>
    </div>
  );
}
