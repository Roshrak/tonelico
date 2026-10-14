import { isDisallowedGemini37Effort } from "./modelPolicy.js";

export interface ValidationResult { valid: boolean; errors: string[]; payload: Record<string, unknown> }

const RESULT_ROLES = ["source-clerk", "locator-clerk", "coverage-clerk", "exam-transcriber"];
const TASK_ROLES = RESULT_ROLES;
const REQUIRED_RESULT_FIELDS = ["status", "role", "scope_echo", "items", "coverage", "uncertainties", "violations"];
const REQUIRED_TASK_FIELDS = ["task_id", "role", "input_bundle", "scope", "acceptance"];

function isObject(value: unknown): value is Record<string, unknown> { return Boolean(value) && typeof value === "object" && !Array.isArray(value); }

function unexpectedFields(value: Record<string, unknown>, allowed: string[]): string[] {
  return Object.keys(value).filter((field) => !allowed.includes(field)).sort().map((field) => `additional property '${field}' not allowed`);
}

function stringArray(value: unknown, field: string): string[] {
  return Array.isArray(value) ? value.map((item, index) => typeof item === "string" ? "" : `${field}[${index}] must be a string`).filter(Boolean) : [`${field} must be an array`];
}

export function validateWorkerResultObject(input: unknown): ValidationResult & { payload: Record<string, unknown> } {
  if (!isObject(input)) return { valid: false, errors: ["Worker result must be an object"], payload: {} };
  const errors = [...unexpectedFields(input, [...REQUIRED_RESULT_FIELDS])];
  for (const field of REQUIRED_RESULT_FIELDS) if (!(field in input)) errors.push(`must have required property '${field}'`);
  if (errors.length) return { valid: false, errors, payload: input };
  if (!["done", "partial", "blocked"].includes(String(input.status))) errors.push("status must be one of done, partial, blocked");
  if (!RESULT_ROLES.includes(String(input.role))) errors.push(`role must be one of ${RESULT_ROLES.join(", ")}`);
  if (!isObject(input.scope_echo)) errors.push("scope_echo must be an object");
  else {
    errors.push(...unexpectedFields(input.scope_echo, ["source_id", "pages"]));
    if (typeof input.scope_echo.source_id !== "string" || !input.scope_echo.source_id.trim()) errors.push("scope_echo.source_id must be a non-empty string");
    if ("pages" in input.scope_echo) {
      const pages = input.scope_echo.pages;
      if (!Array.isArray(pages) || pages.length !== 2 || !pages.every((page) => Number.isInteger(page) && page >= 1)) errors.push("scope_echo.pages must contain two positive integers");
    }
  }
  if (!Array.isArray(input.items)) errors.push("items must be an array");
  else input.items.forEach((rawItem, index) => {
    if (!isObject(rawItem)) {
      errors.push(`items[${index}] must be an object`);
      return;
    }
    errors.push(...unexpectedFields(rawItem, ["id", "text", "locator", "confidence"]).map((error) => `items[${index}].${error}`));
    for (const field of ["id", "text"]) if (typeof rawItem[field] !== "string" || !rawItem[field].trim()) errors.push(`items[${index}].${field} must be a non-empty string`);
    if (!["high", "medium", "low"].includes(String(rawItem.confidence))) errors.push(`items[${index}].confidence must be high, medium, or low`);
    const locator = rawItem.locator;
    if (!isObject(locator)) {
      errors.push(`items[${index}].locator must be an object`);
      return;
    }
    errors.push(...unexpectedFields(locator, ["source_id", "page", "section", "line"]).map((error) => `items[${index}].locator.${error}`));
    if (typeof locator.source_id !== "string" || !locator.source_id.trim()) errors.push(`items[${index}].locator.source_id must be a non-empty string`);
    if ("page" in locator && (!Number.isInteger(locator.page) || Number(locator.page) < 1)) errors.push(`items[${index}].locator.page must be a positive integer`);
    if ("line" in locator && (!Number.isInteger(locator.line) || Number(locator.line) < 1)) errors.push(`items[${index}].locator.line must be a positive integer`);
    if (!("page" in locator) && !("section" in locator) && !("line" in locator)) errors.push(`items[${index}].locator requires page, section, or line`);
  });
  const coverage = input.coverage;
  if (!isObject(coverage)) errors.push("coverage must be an object");
  else {
    errors.push(...unexpectedFields(coverage, ["expected", "covered", "missing"]).map((error) => `coverage.${error}`));
    if (!Number.isInteger(coverage.expected) || Number(coverage.expected) < 0) errors.push("coverage.expected must be a non-negative integer");
    if (!Number.isInteger(coverage.covered) || Number(coverage.covered) < 0) errors.push("coverage.covered must be a non-negative integer");
    errors.push(...stringArray(coverage.missing, "coverage.missing"));
  }
  errors.push(...stringArray(input.uncertainties, "uncertainties"), ...stringArray(input.violations, "violations"));
  if (input.status === "done") {
    const coverage = isObject(input.coverage) ? input.coverage : {};
    if (Array.isArray(coverage.missing) && coverage.missing.length) errors.push("Worker done result has missing coverage");
    if (Number(coverage.covered) !== Number(coverage.expected)) errors.push("Worker done result has missing coverage");
    if (Array.isArray(input.violations) && input.violations.length) errors.push("Worker done result reports violations");
  }
  return { valid: !errors.length, errors: [...new Set(errors)], payload: input };
}

interface SemanticOptions { expected_source_id?: string; expected_pages?: [number, number]; expected_role?: string }

export function validateWorkerSemantics(validation: ValidationResult, options: SemanticOptions = {}): ValidationResult {
  const errors = [...validation.errors];
  const payload = validation.payload;
  if (options.expected_role && payload.role !== options.expected_role) errors.push(`Worker role does not match task: expected ${options.expected_role}, got ${String(payload.role)}`);
  const echo = isObject(payload.scope_echo) ? payload.scope_echo : {};
  if (options.expected_source_id && echo.source_id !== options.expected_source_id) errors.push(`Worker source scope does not match task: expected ${options.expected_source_id}, got ${String(echo.source_id)}`);
  if (options.expected_pages && JSON.stringify(echo.pages) !== JSON.stringify(options.expected_pages)) errors.push(`Worker page scope does not match task: expected ${options.expected_pages[0]}:${options.expected_pages[1]}, got ${JSON.stringify(echo.pages)}`);
  const items = Array.isArray(payload.items) ? payload.items : [];
  items.forEach((rawItem, _index) => {
    if (!isObject(rawItem)) return;
    const locator = isObject(rawItem.locator) ? rawItem.locator : {};
    if (options.expected_source_id && locator.source_id !== options.expected_source_id) errors.push(`Worker item ${String(rawItem.id || "<unknown>")} has an out-of-scope locator`);
    if (options.expected_pages) {
      const [start, end] = options.expected_pages;
      if (!Number.isInteger(locator.page)) errors.push(`Worker item ${String(rawItem.id || "<unknown>")} requires a page locator for a PDF scope`);
      else if (Number(locator.page) < start || Number(locator.page) > end) errors.push(`Worker item ${String(rawItem.id || "<unknown>")} page ${Number(locator.page)} is outside expected pages ${start}:${end}`);
    }
  });
  return { valid: !errors.length, errors: [...new Set(errors)], payload };
}

export function validateTaskObject(input: unknown): ValidationResult {
  if (!isObject(input)) return { valid: false, errors: ["Task must be an object"], payload: {} };
  const errors = [...unexpectedFields(input, REQUIRED_TASK_FIELDS.concat("worker_model"))];
  for (const field of REQUIRED_TASK_FIELDS) if (!(field in input)) errors.push(`must have required property '${field}'`);
  if (errors.length) return { valid: false, errors, payload: input };
  if (typeof input.task_id !== "string" || !input.task_id.trim()) errors.push("task_id must be a non-empty string");
  if (!TASK_ROLES.includes(String(input.role))) errors.push(`role must be one of ${TASK_ROLES.join(", ")}`);
  if (typeof input.input_bundle !== "string" || !input.input_bundle.trim()) errors.push("input_bundle must be a non-empty string");
  const scope = input.scope;
  if (!isObject(scope)) errors.push("scope must be an object");
  else {
    if (typeof scope.source_id !== "string" || !scope.source_id.trim()) errors.push("scope.source_id must be a non-empty string");
    if ("pages" in scope) {
      const pages = scope.pages;
      if (!Array.isArray(pages) || pages.length !== 2 || !pages.every((page) => Number.isInteger(page) && page >= 1)) errors.push("scope.pages must contain two positive integers");
      else if (Number(pages[0]) >= Number(pages[1])) errors.push("scope.pages must use ascending order");
    }
  }
  if (!Array.isArray(input.acceptance) || !input.acceptance.length || !input.acceptance.every((item) => typeof item === "string" && item.trim())) errors.push("acceptance must contain non-empty strings");
  if ("worker_model" in input && input.worker_model !== null && (typeof input.worker_model !== "string" || !input.worker_model.trim())) errors.push("worker_model must be a string or null");
  if (typeof input.worker_model === "string" && isDisallowedGemini37Effort(input.worker_model)) errors.push("model_effort_not_allowed");
  return { valid: !errors.length, errors: [...new Set(errors)], payload: input };
}
