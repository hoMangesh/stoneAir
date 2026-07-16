import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BarChart3,
  Boxes,
  CheckCircle2,
  ClipboardList,
  Factory,
  FileSpreadsheet,
  Gauge,
  Leaf,
  PackageSearch,
  Search,
  Settings2,
  Sparkles,
  Upload,
  Zap,
} from "lucide-react";
import "./styles.css";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

type ProcessBreakdown = {
  step_order: number;
  process_name: string;
  process_group: string;
  country: string;
  energy_kwh: number;
  water_l: number;
  carbon_kgco2e: number;
  machines: string;
  source_status: string;
  confidence: { label: string; score: number; percent: number };
  machine_models: string[];
  process_steps: Array<{ step_name: string; sequence: number }>;
};

type MachineBreakdown = {
  step_order: number;
  process_name: string;
  machine_category: string;
  machine_model_id: string;
  machine_model: string;
  unit: string;
  electricity_rate: number;
  electricity_kwh: number;
  water_l: number;
  brochure_url: string;
  datasheet_url: string;
  confidence: { label: string; score: number; percent: number };
  source: string;
};

type ActivityTrace = {
  activity_type: string;
  process_name: string;
  machine_model_id: string;
  machine_model: string;
  machine_category: string;
  activity_quantity: number;
  activity_unit: string;
  factor_id: string;
  factor: number;
  factor_unit: string;
  carbon_kgco2e: number;
  source: string;
  approval_status: string;
  confidence: { label: string; score: number; percent: number };
};

type InferenceTrace = {
  summary: {
    record_count: number;
    seed_record_count: number;
    storage_policy: string;
    next_persistence_target: string;
  };
  records: Array<{
    inference_id: string;
    inference_type: string;
    input_data: string;
    output_data: string;
    agent: string;
    confidence: { label: string; score: number; percent: number };
    timestamp: string;
    version: string;
    source: string;
    approval_status: string;
    evidence: string[];
  }>;
};

type MasterDomains = {
  principles: string[];
  domains: Array<{ domain: string; entity_count: number }>;
  operational_domains: Array<{ domain: string; entity_count: number }>;
};

type MachineRepository = {
  summary: {
    machine_models: number;
    brochure_records: number;
    spec_extraction_records: number;
    energy_profiles: number;
    source_status: Record<string, number>;
    extraction_status: Record<string, number>;
  };
  records: Array<{
    machine_model_id: string;
    manufacturer: string;
    model: string;
    machine_category: string;
    process: string;
    brochure: {
      source_status?: string;
      extraction_status?: string;
      public_url?: string;
      notes?: string;
      approval_status?: string;
    };
    factory_installations: number;
    confidence: { label: string; score: number; percent: number };
    next_action: string;
  }>;
  extraction_fields: string[];
};

type MachineSpecExtraction = {
  machine_model_id: string;
  source: string;
  extracted_fields: Record<
    "power" | "throughput" | "capacity" | "liquor_ratio",
    Array<Record<string, string>>
  >;
  candidate_record_count: number;
  confidence: { label: string; score: number; percent: number };
  storage_policy: string;
};

type BomComponent = {
  material: string;
  percent: number | null;
  weight_g: number | null;
  origin: string | null;
};

type WorkflowStep = {
  process: string;
  description: string;
  optional: boolean;
  machines: { name: string; category: string; purpose: string; automation: string }[];
};

type DynamicWorkflow = {
  resolved: {
    product_name: string;
    category: string;
    product_type: string;
    material: string;
    fabric_structure: string;
    features: string[];
  };
  workflow: WorkflowStep[];
  confidence: { label: string; score: number; percent: number };
  machine_count: number;
  process_count: number;
  source: string;
};

type Persisted = {
  run_id: string;
  storage: string;
  inference_records_stored: number;
  activity_records_stored: number;
};

type Analysis = {
  signals: {
    product_hint: string | null;
    keywords: string[];
    blend: Array<{ material: string; percent: number }>;
    gsm: number | null;
    weight_g: number | null;
    bom_components: BomComponent[];
    declared_origin: string | null;
    provenance: Record<string, string>;
  };
  inference_trace: InferenceTrace;
  product: {
    taxonomy_id: string;
    domain: string;
    family: string;
    category: string;
    product_type: string;
    variant: string;
    template_id: string;
    template_name: string;
    weight_g: number;
    gsm: number | null;
    material_blend: string | Array<{ material: string; percent: number }>;
  };
  confidence: {
    overall: number;
    classification: number;
    route: number;
    match_score: number;
    alternatives: Array<{ taxonomy_id: string; product_type: string; variant: string; score: number }>;
  };
  route: {
    route_id: string;
    route_name: string;
    confidence: number;
    source_mix: { kg_backed: number; inferred: number; total: number };
  };
  impact: {
    energy_kwh: number;
    water_l: number;
    carbon_kgco2e: number;
    transport_carbon_kgco2e?: number;
    chemical_carbon_kgco2e?: number;
  };
  impact_breakdown?: {
    electricity_carbon_kgco2e: number;
    transport_carbon_kgco2e: number;
    chemical_carbon_kgco2e: number;
  };
  dynamic_workflow: DynamicWorkflow | null;
  persisted: Persisted | null;
  process_breakdown: ProcessBreakdown[];
  machine_breakdown: MachineBreakdown[];
  activity_trace: ActivityTrace[];
  chemical_inventory: Record<string, number>;
  digital_product_passport: {
    product_type: string;
    route_id: string;
    template_id: string;
    kg_coverage: string;
    source_status: { kg_backed: number; inferred: number; total: number };
    principles: string[];
  };
};

const sampleDescription =
  "Basic cotton t-shirt, crew neck short sleeve, 180 gsm single jersey, 100% cotton, adult medium, reactive dyed.";

function formatBlend(blend: Analysis["product"]["material_blend"]) {
  if (Array.isArray(blend)) {
    return blend.map((item) => `${item.percent}% ${item.material}`).join(", ");
  }
  return blend;
}

function MetricCard({
  label,
  value,
  unit,
  icon,
}: {
  label: string;
  value: string | number;
  unit: string;
  icon: React.ReactNode;
}) {
  return (
    <section className="metric-card">
      <div className="metric-icon">{icon}</div>
      <div>
        <p>{label}</p>
        <strong>
          {value} <span>{unit}</span>
        </strong>
      </div>
    </section>
  );
}

function LayerMap({ analysis }: { analysis: Analysis | null }) {
  const layers = [
    {
      title: "Document Intelligence",
      description: "PDF/Excel parsing, BOM extraction, blend parser",
      Icon: FileSpreadsheet,
    },
    {
      title: "Product Intelligence",
      description: "Classification, taxonomy, template, confidence",
      Icon: PackageSearch,
    },
    {
      title: "Manufacturing Reconstruction",
      description: "Route, process, provenance, supplier defaults",
      Icon: Factory,
    },
    {
      title: "Machine Intelligence",
      description: "Machine mapping and capability matching",
      Icon: Boxes,
    },
    {
      title: "Energy Reconstruction",
      description: "Energy, throughput, yield, water, waste models",
      Icon: Zap,
    },
    {
      title: "Emission Engine",
      description: "Grid, fuel, transport, chemical factors",
      Icon: Leaf,
    },
    {
      title: "Analytics & Reporting",
      description: "Carbon, water, chemical inventory, passport",
      Icon: BarChart3,
    },
  ];

  return (
    <section className="layer-map" aria-label="Platform architecture status">
      {layers.map(({ title, description, Icon }, index) => (
        <article className={analysis ? "layer active" : "layer"} key={title}>
          <div className="layer-topline">
            <Icon size={18} />
            <span>{String(index + 1).padStart(2, "0")}</span>
          </div>
          <h3>{title}</h3>
          <p>{description}</p>
        </article>
      ))}
    </section>
  );
}

function ProcessExplorer({ rows }: { rows: ProcessBreakdown[] }) {
  return (
    <section className="panel process-panel">
      <div className="panel-heading">
        <Factory size={18} />
        <h2>Process Explorer</h2>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Step</th>
              <th>Process</th>
              <th>Country</th>
              <th>Machine</th>
              <th>Energy</th>
              <th>Water</th>
              <th>Carbon</th>
              <th>Source</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.step_order}-${row.process_name}`}>
                <td>{row.step_order}</td>
                <td>
                  <strong>{row.process_name}</strong>
                  <span>{row.process_group}</span>
                </td>
                <td>{row.country || "TBD"}</td>
                <td>{row.machines || "Model pending"}</td>
                <td>{row.energy_kwh.toFixed(3)}</td>
                <td>{row.water_l.toFixed(1)}</td>
                <td>{row.carbon_kgco2e.toFixed(3)}</td>
                <td>{row.source_status}</td>
                <td>{row.confidence.label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function MachineExplorer({ rows }: { rows: MachineBreakdown[] }) {
  return (
    <section className="panel process-panel">
      <div className="panel-heading">
        <Boxes size={18} />
        <h2>Machine Energy Intelligence</h2>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Step</th>
              <th>Process</th>
              <th>Machine Model</th>
              <th>Activity Unit</th>
              <th>Rate</th>
              <th>Energy</th>
              <th>Brochure</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.step_order}-${row.machine_model_id}`}>
                <td>{row.step_order}</td>
                <td>
                  <strong>{row.process_name}</strong>
                  <span>{row.machine_category}</span>
                </td>
                <td>
                  <strong>{row.machine_model}</strong>
                  <span>{row.machine_model_id}</span>
                </td>
                <td>{row.unit}</td>
                <td>{row.electricity_rate}</td>
                <td>{row.electricity_kwh.toFixed(3)} kWh</td>
                <td>{row.brochure_url.includes("TBD") ? "Pending review" : "Available"}</td>
                <td>{row.confidence.label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ActivityTracePanel({ rows }: { rows: ActivityTrace[] }) {
  return (
    <section className="panel process-panel">
      <div className="panel-heading">
        <ClipboardList size={18} />
        <h2>Activity Data Trace</h2>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Activity</th>
              <th>Process</th>
              <th>Machine</th>
              <th>Quantity</th>
              <th>Emission Factor</th>
              <th>Carbon</th>
              <th>Approval</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={`${row.factor_id}-${row.machine_model_id}-${index}`}>
                <td>{row.activity_type}</td>
                <td>{row.process_name}</td>
                <td>{row.machine_model}</td>
                <td>
                  {row.activity_quantity.toFixed(4)} {row.activity_unit}
                </td>
                <td>
                  <strong>{row.factor_id}</strong>
                  <span>
                    {row.factor} {row.factor_unit}
                  </span>
                </td>
                <td>{row.carbon_kgco2e.toFixed(4)} kgCO2e</td>
                <td>{row.approval_status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function InferenceTracePanel({ trace }: { trace: InferenceTrace }) {
  return (
    <section className="panel process-panel">
      <div className="panel-heading">
        <Gauge size={18} />
        <h2>Inference Engine Trace</h2>
      </div>
      <div className="repo-summary">
        <span>{trace.summary.record_count} runtime records</span>
        <span>{trace.summary.seed_record_count} seed records</span>
        <span>{trace.summary.next_persistence_target}</span>
      </div>
      <p className="trace-policy">{trace.summary.storage_policy}</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Inference</th>
              <th>Agent</th>
              <th>Output</th>
              <th>Evidence</th>
              <th>Source</th>
              <th>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {trace.records.map((row) => (
              <tr key={row.inference_id}>
                <td>
                  <strong>{row.inference_type}</strong>
                  <span>{row.inference_id}</span>
                </td>
                <td>{row.agent}</td>
                <td>{row.output_data}</td>
                <td>{row.evidence.join("; ")}</td>
                <td>{row.source}</td>
                <td>{row.confidence.label}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function MachineBrochurePanel({ repository }: { repository: MachineRepository | null }) {
  return (
    <section className="panel process-panel">
      <div className="panel-heading">
        <FileSpreadsheet size={18} />
        <h2>Machine Brochure Repository</h2>
      </div>
      {repository ? (
        <>
          <div className="repo-summary">
            <span>{repository.summary.machine_models} models</span>
            <span>{repository.summary.brochure_records} brochure records</span>
            <span>{repository.summary.energy_profiles} energy profiles</span>
            <span>{repository.summary.spec_extraction_records} extracted specs</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Machine Model</th>
                  <th>Process</th>
                  <th>Brochure</th>
                  <th>Extraction</th>
                  <th>Factory Qty</th>
                  <th>Next Action</th>
                  <th>Confidence</th>
                </tr>
              </thead>
              <tbody>
                {repository.records.map((row) => (
                  <tr key={row.machine_model_id}>
                    <td>
                      <strong>
                        {row.manufacturer} {row.model}
                      </strong>
                      <span>{row.machine_category}</span>
                    </td>
                    <td>{row.process}</td>
                    <td>{row.brochure.source_status ?? "Missing"}</td>
                    <td>{row.brochure.extraction_status ?? "Not Extracted"}</td>
                    <td>{row.factory_installations}</td>
                    <td>{row.next_action}</td>
                    <td>{row.confidence.label}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p>Loading machine brochure repository...</p>
      )}
    </section>
  );
}

function MachineSpecWorkbench({ repository }: { repository: MachineRepository | null }) {
  const [machineModelId, setMachineModelId] = useState("MMOD001");
  const [brochureText, setBrochureText] = useState(
    "Thies iMaster H2O dyeing machine. Nominal batch capacity 250 kg. Installed power 18 kW. Liquor ratio 1:4.5. Throughput 120 kg/h.",
  );
  const [result, setResult] = useState<MachineSpecExtraction | null>(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);

  async function runExtraction(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsExtracting(true);
    setExtractError(null);

    const formData = new FormData();
    formData.append("machine_model_id", machineModelId);
    formData.append("brochure_text", brochureText);

    try {
      const response = await fetch(`${API_BASE}/api/machine-spec-extract`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }
      setResult((await response.json()) as MachineSpecExtraction);
    } catch (caught) {
      setExtractError(caught instanceof Error ? caught.message : "Unable to extract specs");
    } finally {
      setIsExtracting(false);
    }
  }

  const candidates = result
    ? Object.entries(result.extracted_fields).flatMap(([fieldName, matches]) =>
        matches.map((match, index) => ({ fieldName, index, match })),
      )
    : [];

  return (
    <section className="panel spec-workbench">
      <div className="panel-heading">
        <Settings2 size={18} />
        <h2>Machine Spec Extraction Workbench</h2>
      </div>
      <form onSubmit={runExtraction}>
        <label htmlFor="machine-model">Machine Model</label>
        <select
          id="machine-model"
          value={machineModelId}
          onChange={(event) => setMachineModelId(event.target.value)}
        >
          {(repository?.records ?? []).map((record) => (
            <option key={record.machine_model_id} value={record.machine_model_id}>
              {record.manufacturer} {record.model} - {record.machine_category}
            </option>
          ))}
        </select>
        <label htmlFor="brochure-text">Brochure or Datasheet Text</label>
        <textarea
          id="brochure-text"
          value={brochureText}
          onChange={(event) => setBrochureText(event.target.value)}
        />
        <button type="submit" disabled={isExtracting || !brochureText.trim()}>
          {isExtracting ? "Extracting..." : "Extract Candidate Specs"}
        </button>
      </form>
      {extractError && <p className="error">{extractError}</p>}
      {result && (
        <div className="extraction-result">
          <div className="repo-summary">
            <span>{result.candidate_record_count} candidates</span>
            <span>{result.confidence.label}</span>
            <span>{result.source}</span>
          </div>
          <p>{result.storage_policy}</p>
          {candidates.length ? (
            <div className="candidate-grid">
              {candidates.map(({ fieldName, index, match }) => (
                <article key={`${fieldName}-${index}`} className="candidate-card">
                  <span>{fieldName.replace("_", " ")}</span>
                  <strong>{match.raw}</strong>
                  <small>
                    {[match.value, match.unit, match.denominator ? `:${match.denominator}` : ""]
                      .filter(Boolean)
                      .join(" ")}
                  </small>
                </article>
              ))}
            </div>
          ) : (
            <p>No candidate specifications found.</p>
          )}
        </div>
      )}
    </section>
  );
}

function App() {
  const [description, setDescription] = useState(sampleDescription);
  const [files, setFiles] = useState<FileList | null>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [masterDomains, setMasterDomains] = useState<MasterDomains | null>(null);
  const [machineRepository, setMachineRepository] = useState<MachineRepository | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Structured BOM: materials + weight + origin, the primary accurate input path.
  const [components, setComponents] = useState<BomComponent[]>([
    { material: "cotton", percent: 100, weight_g: 215, origin: "India" },
  ]);

  const chemicalRows = useMemo(() => Object.entries(analysis?.chemical_inventory ?? {}), [analysis]);

  useEffect(() => {
    fetch(`${API_BASE}/api/master-domains`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => setMasterDomains(payload as MasterDomains | null))
      .catch(() => setMasterDomains(null));

    fetch(`${API_BASE}/api/machine-intelligence`)
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => setMachineRepository(payload as MachineRepository | null))
      .catch(() => setMachineRepository(null));
  }, []);

  async function runAnalysis(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsLoading(true);
    setError(null);

    const formData = new FormData();
    formData.append("product_description", description);
    // Structured BOM (materials + weight + origin) is the primary accurate path.
    formData.append("bom", JSON.stringify({ components }));
    const declaredOrigin = components.find((component) => component.origin)?.origin ?? "";
    if (declaredOrigin) formData.append("origin", declaredOrigin);
    const selectedFiles: File[] = files ? Array.from(files) : [];
    selectedFiles.forEach((file) => formData.append("files", file));

    try {
      const response = await fetch(`${API_BASE}/api/analyze`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(`API returned ${response.status}`);
      }
      setAnalysis((await response.json()) as Analysis);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to run analysis");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main>
      <header className="app-header">
        <div>
          <span className="eyebrow">
            <Sparkles size={16} />
            Manufacturing Intelligence Engine
          </span>
          <h1>Sustainable Fashion Carbon Intelligence</h1>
          <p>
            Upload or describe an apparel or footwear product and reconstruct its product template,
            manufacturing route, machine map, resources, emissions, and confidence trail.
          </p>
        </div>
        <div className="header-actions">
          <button type="button" className="icon-button" title="Product search">
            <Search size={20} />
          </button>
          <button type="button" className="icon-button" title="Reports">
            <ClipboardList size={20} />
          </button>
        </div>
      </header>

      <section className="workspace">
        <form className="input-panel" onSubmit={runAnalysis}>
          <div className="panel-heading">
            <Upload size={18} />
            <h2>Product Intake</h2>
          </div>
          <label htmlFor="description">Product Description</label>
          <textarea
            id="description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
          <div className="bom-editor">
            <div className="bom-editor-head">
              <span>Bill of Materials</span>
              <button
                type="button"
                className="bom-add"
                onClick={() =>
                  setComponents([...components, { material: "", percent: null, weight_g: null, origin: "" }])
                }
              >
                + Add line
              </button>
            </div>
            {components.map((component, index) => (
              <div className="bom-row" key={index}>
                <input
                  className="bom-material"
                  placeholder="Material"
                  value={component.material}
                  onChange={(event) =>
                    setComponents(
                      components.map((c, i) => (i === index ? { ...c, material: event.target.value } : c)),
                    )
                  }
                />
                <input
                  className="bom-pct"
                  placeholder="%"
                  type="number"
                  value={component.percent ?? ""}
                  onChange={(event) =>
                    setComponents(
                      components.map((c, i) =>
                        i === index ? { ...c, percent: event.target.value ? Number(event.target.value) : null } : c,
                      ),
                    )
                  }
                />
                <input
                  className="bom-weight"
                  placeholder="g"
                  type="number"
                  value={component.weight_g ?? ""}
                  onChange={(event) =>
                    setComponents(
                      components.map((c, i) =>
                        i === index ? { ...c, weight_g: event.target.value ? Number(event.target.value) : null } : c,
                      ),
                    )
                  }
                />
                <input
                  className="bom-origin"
                  placeholder="Origin"
                  value={component.origin ?? ""}
                  onChange={(event) =>
                    setComponents(
                      components.map((c, i) => (i === index ? { ...c, origin: event.target.value } : c)),
                    )
                  }
                />
                <button
                  type="button"
                  className="bom-remove"
                  onClick={() => setComponents(components.filter((_, i) => i !== index))}
                  aria-label="Remove material line"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          <label className="file-input" htmlFor="file-upload">
            <FileSpreadsheet size={18} />
            <span>{files?.length ? `${files.length} file selected` : "Upload BOM or tech pack"}</span>
          </label>
          <input
            id="file-upload"
            type="file"
            multiple
            onChange={(event) => setFiles(event.target.files)}
          />
          <button type="submit" disabled={isLoading}>
            {isLoading ? "Reconstructing..." : "Run Intelligence"}
          </button>
          {error && <p className="error">{error}</p>}
        </form>

        <section className="result-panel">
          {analysis ? (
            <>
              <div className="product-summary">
                <div>
                  <span className="eyebrow">Matched Product</span>
                  <h2>{analysis.product.template_name}</h2>
                  <p>
                    {analysis.product.domain} / {analysis.product.family} / {analysis.product.category}
                  </p>
                </div>
                <div className="confidence-pill">
                  <Gauge size={18} />
                  {(analysis.confidence.overall * 100).toFixed(0)}%
                </div>
              </div>

              <div className="metrics">
                <MetricCard
                  label="Carbon Footprint"
                  value={analysis.impact.carbon_kgco2e.toFixed(3)}
                  unit="kgCO2e"
                  icon={<Leaf size={20} />}
                />
                <MetricCard
                  label="Water Footprint"
                  value={analysis.impact.water_l.toFixed(1)}
                  unit="L"
                  icon={<BarChart3 size={20} />}
                />
                <MetricCard
                  label="Energy"
                  value={analysis.impact.energy_kwh.toFixed(3)}
                  unit="kWh"
                  icon={<Zap size={20} />}
                />
              </div>

              {analysis.impact_breakdown && (
                <section className="panel emission-breakdown" aria-label="Carbon emission breakdown">
                  <div className="panel-heading">
                    <Leaf size={18} />
                    <h2>Carbon Breakdown</h2>
                  </div>
                  <ul className="breakdown-list">
                    <li>
                      <span>Electricity</span>
                      <strong>{analysis.impact_breakdown.electricity_carbon_kgco2e.toFixed(4)} kgCO2e</strong>
                    </li>
                    <li>
                      <span>Transport</span>
                      <strong>{analysis.impact_breakdown.transport_carbon_kgco2e.toFixed(4)} kgCO2e</strong>
                    </li>
                    <li>
                      <span>Chemicals</span>
                      <strong>{analysis.impact_breakdown.chemical_carbon_kgco2e.toFixed(4)} kgCO2e</strong>
                    </li>
                  </ul>
                </section>
              )}

              {analysis.dynamic_workflow && (
                <section className="panel workflow-panel" aria-label="Dynamic machine workflow">
                  <div className="panel-heading">
                    <Boxes size={18} />
                    <h2>Dynamic Machine Workflow</h2>
                  </div>
                  <div className="repo-summary">
                    <span>{analysis.dynamic_workflow.resolved.product_type} / {analysis.dynamic_workflow.resolved.material}</span>
                    <span>{analysis.dynamic_workflow.process_count} processes</span>
                    <span>{analysis.dynamic_workflow.machine_count} machines</span>
                    <span>{analysis.dynamic_workflow.confidence.label}</span>
                  </div>
                  <p className="trace-policy">{analysis.dynamic_workflow.source}</p>
                  <ul className="workflow-list">
                    {analysis.dynamic_workflow.workflow.map((step) => (
                      <li key={step.process}>
                        <strong>
                          {step.process}
                          {step.optional ? <em> · optional</em> : null}
                        </strong>
                        <span>{step.machines.map((machine) => machine.name).join(" · ") || "no machines mapped"}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {analysis.persisted && (
                <p className="persisted-note">
                  <CheckCircle2 size={14} />
                  Run {analysis.persisted.run_id} persisted to {analysis.persisted.storage} ·{" "}
                  {analysis.persisted.inference_records_stored} inference records ·{" "}
                  {analysis.persisted.activity_records_stored} activity rows
                </p>
              )}

              <div className="detail-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <PackageSearch size={18} />
                    <h2>Template Match</h2>
                  </div>
                  <dl>
                    <dt>Taxonomy</dt>
                    <dd>{analysis.product.taxonomy_id}</dd>
                    <dt>Route</dt>
                    <dd>{analysis.route.route_id}</dd>
                    <dt>Blend</dt>
                    <dd>{formatBlend(analysis.product.material_blend)}</dd>
                    <dt>Weight</dt>
                    <dd>{analysis.product.weight_g} g</dd>
                    <dt>GSM</dt>
                    <dd>{analysis.product.gsm ?? "N/A"}</dd>
                  </dl>
                </section>

                <section className="panel">
                  <div className="panel-heading">
                    <CheckCircle2 size={18} />
                    <h2>Digital Passport</h2>
                  </div>
                  <dl>
                    <dt>KG coverage</dt>
                    <dd>{analysis.digital_product_passport.kg_coverage}</dd>
                    <dt>KG-backed steps</dt>
                    <dd>
                      {analysis.route.source_mix.kg_backed} / {analysis.route.source_mix.total}
                    </dd>
                    <dt>Inferred steps</dt>
                    <dd>{analysis.route.source_mix.inferred}</dd>
                    <dt>Route confidence</dt>
                    <dd>{(analysis.route.confidence * 100).toFixed(0)}%</dd>
                  </dl>
                </section>

                <section className="panel">
                  <div className="panel-heading">
                    <Leaf size={18} />
                    <h2>Chemical Inventory</h2>
                  </div>
                  {chemicalRows.length ? (
                    <ul className="chemical-list">
                      {chemicalRows.map(([name, grams]) => (
                        <li key={name}>
                          <span>{name}</span>
                          <strong>{grams.toFixed(2)} g</strong>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p>No chemical model matched this route yet.</p>
                  )}
                </section>

                <section className="panel">
                  <div className="panel-heading">
                    <Boxes size={18} />
                    <h2>Master Domains</h2>
                  </div>
                  {masterDomains ? (
                    <ul className="domain-list">
                      {masterDomains.domains.slice(0, 6).map((domain) => (
                        <li key={domain.domain}>
                          <span>{domain.domain}</span>
                          <strong>{domain.entity_count}</strong>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p>Loading master domains...</p>
                  )}
                </section>
              </div>

              <InferenceTracePanel trace={analysis.inference_trace} />
              <ProcessExplorer rows={analysis.process_breakdown} />
              <MachineExplorer rows={analysis.machine_breakdown} />
              <MachineBrochurePanel repository={machineRepository} />
              <MachineSpecWorkbench repository={machineRepository} />
              <ActivityTracePanel rows={analysis.activity_trace} />
            </>
          ) : (
            <div className="empty-state">
              <Sparkles size={34} />
              <h2>Ready for reconstruction</h2>
              <p>
                Run the sample product or upload a BOM/tech pack to activate the intelligence layers.
              </p>
            </div>
          )}
        </section>
      </section>

      <LayerMap analysis={analysis} />
      {masterDomains && (
        <section className="principle-strip" aria-label="Architecture principles">
          {masterDomains.principles.map((principle) => (
            <span key={principle}>{principle}</span>
          ))}
        </section>
      )}
    </main>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
