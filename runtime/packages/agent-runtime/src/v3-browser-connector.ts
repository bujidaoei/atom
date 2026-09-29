import { Type, type Static, type TSchema } from 'typebox';
import { Value } from 'typebox/value';

import type { V3BrowserConnectorState } from '../../product-contracts/src/v3.ts';
import type { PiToolResult, ToolDefinition } from './pi-runtime-types.ts';

export const V3_BROWSER_CONTEXT_EMPTY_RESULT =
  'No MCP tab group exists. Use createIfEmpty: true to create one.';

const BROWSER_TOOL_UNAVAILABLE = 'Browser Connector is unavailable for this Waker.';
const BROWSER_PAGE_UNAVAILABLE = 'Browser selected-page authorization is unavailable.';
const INVALID_INPUT = 'Browser Connector rejected invalid tool parameters.';
const INVALID_RESULT = 'Browser Connector returned an invalid or over-limit result.';
const JAVASCRIPT_REJECTED = 'Browser JavaScript policy rejected the expression.';

const CONTEXT_TOOL = 'mcp__plugin_builtin_browser__tabs_context_mcp';
const READ_PAGE_TOOL = 'mcp__plugin_builtin_browser__read_page';
const GET_PAGE_TEXT_TOOL = 'mcp__plugin_builtin_browser__get_page_text';
const JAVASCRIPT_TOOL = 'mcp__plugin_builtin_browser__javascript_tool';

const ContextParameters = Type.Object({}, { additionalProperties: false });
const ReadPageParameters = Type.Object(
  {
    filter: Type.Optional(Type.Union([Type.Literal('interactive'), Type.Literal('all')])),
    depth: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
    max_chars: Type.Optional(Type.Integer({ minimum: 1_000, maximum: 200_000 })),
  },
  { additionalProperties: false },
);
const GetPageTextParameters = Type.Object(
  { max_chars: Type.Optional(Type.Integer({ minimum: 1_000, maximum: 200_000 })) },
  { additionalProperties: false },
);
const JavascriptParameters = Type.Object(
  { text: Type.String({ minLength: 1, maxLength: 4_096 }) },
  { additionalProperties: false },
);

export type V3BrowserConnectorRuntimeState = Pick<
  V3BrowserConnectorState,
  'browserContextToolAvailable' | 'browserPageToolReady'
>;

export type V3BrowserHostMethod = 'tabs_context_mcp' | 'read_page' | 'get_page_text' | 'javascript_tool';

export interface V3BrowserHostInvocation {
  ownerId: string;
  wakerId: string;
  method: V3BrowserHostMethod;
  input: Record<string, unknown>;
}

export interface V3BrowserToolHostPort {
  getState(
    input: { ownerId: string; wakerId: string },
    signal?: AbortSignal,
  ): Promise<V3BrowserConnectorRuntimeState>;
  invoke(input: V3BrowserHostInvocation, signal: AbortSignal): Promise<string>;
}

export interface LoadV3BrowserConnectorToolsOptions {
  ownerId: string;
  wakerId: string;
  subjectType: 'waker' | 'group' | 'cloud';
  host?: V3BrowserToolHostPort;
  deadlineMs?: number;
}

class BrowserToolDeadlineError extends Error {
  constructor() {
    super('Browser Connector tool exceeded its execution deadline.');
  }
}

function failure(text: string): PiToolResult {
  return { content: [{ type: 'text', text }], isError: true };
}

function completed(text: string): PiToolResult {
  return { content: [{ type: 'text', text }], isError: false };
}

function deadline(options: LoadV3BrowserConnectorToolsOptions): number {
  const value = options.deadlineMs ?? 8_000;
  if (!Number.isSafeInteger(value) || value < 10 || value > 30_000) {
    throw new Error('Browser Connector deadline is invalid.');
  }
  return value;
}

async function boundedHostCall<T>(
  operation: (signal: AbortSignal) => Promise<T>,
  signal: AbortSignal | undefined,
  deadlineMs: number,
): Promise<T> {
  signal?.throwIfAborted();
  const controller = new AbortController();
  const onAbort = () => controller.abort(signal?.reason);
  signal?.addEventListener('abort', onAbort, { once: true });
  const timer = setTimeout(() => controller.abort(new BrowserToolDeadlineError()), deadlineMs);
  timer.unref?.();
  const aborted = new Promise<never>((_resolve, reject) => {
    controller.signal.addEventListener(
      'abort',
      () => reject(controller.signal.reason ?? new BrowserToolDeadlineError()),
      { once: true },
    );
  });
  try {
    return await Promise.race([operation(controller.signal), aborted]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}

function assertRuntimeState(value: unknown): asserts value is V3BrowserConnectorRuntimeState {
  if (
    typeof value !== 'object' ||
    value === null ||
    typeof (value as V3BrowserConnectorRuntimeState).browserContextToolAvailable !== 'boolean' ||
    typeof (value as V3BrowserConnectorRuntimeState).browserPageToolReady !== 'boolean'
  ) {
    throw new Error('Browser Connector host returned an invalid state.');
  }
}

async function currentState(
  options: LoadV3BrowserConnectorToolsOptions & { host: V3BrowserToolHostPort },
  signal: AbortSignal | undefined,
  deadlineMs: number,
): Promise<V3BrowserConnectorRuntimeState> {
  let value: unknown;
  try {
    value = await boundedHostCall(
      (boundedSignal) =>
        options.host.getState({ ownerId: options.ownerId, wakerId: options.wakerId }, boundedSignal),
      signal,
      deadlineMs,
    );
  } catch (cause) {
    signal?.throwIfAborted();
    if (cause instanceof BrowserToolDeadlineError) throw cause;
    throw new Error(BROWSER_TOOL_UNAVAILABLE, { cause });
  }
  assertRuntimeState(value);
  return value;
}

function assertBoundedHostResult(value: unknown, maximumBytes: number): asserts value is string {
  if (typeof value !== 'string' || value.includes('\0') || Buffer.byteLength(value, 'utf8') > maximumBytes) {
    throw new Error(INVALID_RESULT);
  }
}

async function dispatch(
  options: LoadV3BrowserConnectorToolsOptions & { host: V3BrowserToolHostPort },
  method: V3BrowserHostMethod,
  input: Record<string, unknown>,
  signal: AbortSignal | undefined,
  deadlineMs: number,
  maximumResultBytes: number,
): Promise<PiToolResult> {
  let result: unknown;
  try {
    result = await boundedHostCall(
      (boundedSignal) =>
        options.host.invoke(
          { ownerId: options.ownerId, wakerId: options.wakerId, method, input },
          boundedSignal,
        ),
      signal,
      deadlineMs,
    );
  } catch (cause) {
    signal?.throwIfAborted();
    if (cause instanceof BrowserToolDeadlineError) throw cause;
    throw new Error('Browser Connector host rejected the tool invocation.', { cause });
  }
  assertBoundedHostResult(result, maximumResultBytes);
  return completed(result);
}

function checkedParameters<T extends TSchema>(schema: T, value: unknown): Static<T> | undefined {
  return Value.Check(schema, value) ? (value as Static<T>) : undefined;
}

type TokenKind = 'identifier' | 'number' | 'string' | 'operator' | 'eof';
interface Token {
  kind: TokenKind;
  value: string;
}

type JavascriptExpression =
  | { type: 'identifier'; name: string }
  | { type: 'literal'; value: string | number | boolean | null }
  | { type: 'unary'; operator: string; argument: JavascriptExpression }
  | {
      type: 'binary';
      operator: string;
      left: JavascriptExpression;
      right: JavascriptExpression;
    }
  | {
      type: 'conditional';
      test: JavascriptExpression;
      consequent: JavascriptExpression;
      alternate: JavascriptExpression;
    }
  | {
      type: 'member';
      object: JavascriptExpression;
      property: JavascriptExpression;
      computed: boolean;
      optional: boolean;
    }
  | { type: 'call'; callee: JavascriptExpression; arguments: JavascriptExpression[] };

export type V3BrowserJavascriptExpression = JavascriptExpression;

function tokenizeJavascript(source: string): Token[] {
  const tokens: Token[] = [];
  let index = 0;
  const push = (kind: TokenKind, value: string) => {
    tokens.push({ kind, value });
    if (tokens.length > 512) throw new Error(JAVASCRIPT_REJECTED);
  };
  while (index < source.length) {
    const character = source[index]!;
    if (/\s/u.test(character)) {
      index += 1;
      continue;
    }
    if (character === '"' || character === "'") {
      const quote = character;
      let raw = '';
      index += 1;
      let closed = false;
      while (index < source.length) {
        const next = source[index]!;
        if (next === quote) {
          closed = true;
          index += 1;
          break;
        }
        if (next === '\n' || next === '\r') throw new Error(JAVASCRIPT_REJECTED);
        if (next === '\\') {
          const escaped = source[index + 1];
          if (!escaped || escaped === '\n' || escaped === '\r') throw new Error(JAVASCRIPT_REJECTED);
          if (escaped === quote || escaped === '\\') {
            raw += escaped;
            index += 2;
            continue;
          }
          const simpleEscapes: Record<string, string> = {
            b: '\b',
            f: '\f',
            n: '\n',
            r: '\r',
            t: '\t',
            v: '\v',
          };
          if (escaped in simpleEscapes) {
            raw += simpleEscapes[escaped];
            index += 2;
            continue;
          }
          const hexLength = escaped === 'x' ? 2 : escaped === 'u' ? 4 : 0;
          const digits = hexLength ? source.slice(index + 2, index + 2 + hexLength) : '';
          if (!hexLength || digits.length !== hexLength || !/^[0-9a-f]+$/iu.test(digits)) {
            throw new Error(JAVASCRIPT_REJECTED);
          }
          raw += String.fromCodePoint(Number.parseInt(digits, 16));
          index += 2 + hexLength;
          continue;
        }
        raw += next;
        index += 1;
      }
      if (!closed || raw.length > 1_000) throw new Error(JAVASCRIPT_REJECTED);
      push('string', raw);
      continue;
    }
    const identifier = /^[A-Za-z_$][A-Za-z0-9_$]*/u.exec(source.slice(index));
    if (identifier) {
      push('identifier', identifier[0]);
      index += identifier[0].length;
      continue;
    }
    const number = /^(?:0|[1-9]\d*)(?:\.\d+)?/u.exec(source.slice(index));
    if (number) {
      push('number', number[0]);
      index += number[0].length;
      continue;
    }
    const operator = [
      '===',
      '!==',
      '?.',
      '??',
      '&&',
      '||',
      '==',
      '!=',
      '<=',
      '>=',
      '.',
      '(',
      ')',
      '[',
      ']',
      ',',
      '?',
      ':',
      '!',
      '+',
      '-',
      '*',
      '/',
      '%',
      '<',
      '>',
    ].find((candidate) => source.startsWith(candidate, index));
    if (!operator) throw new Error(JAVASCRIPT_REJECTED);
    push('operator', operator);
    index += operator.length;
  }
  tokens.push({ kind: 'eof', value: '' });
  return tokens;
}

class ReadOnlyJavascriptParser {
  private index = 0;
  private nodes = 0;

  constructor(private readonly tokens: readonly Token[]) {}

  parse(): JavascriptExpression {
    const expression = this.parseConditional();
    if (this.peek().kind !== 'eof') throw new Error(JAVASCRIPT_REJECTED);
    return expression;
  }

  private node<T extends JavascriptExpression>(value: T): T {
    this.nodes += 1;
    if (this.nodes > 128) throw new Error(JAVASCRIPT_REJECTED);
    return value;
  }

  private peek(): Token {
    return this.tokens[this.index] ?? { kind: 'eof', value: '' };
  }

  private take(value?: string): Token {
    const token = this.peek();
    if (value !== undefined && token.value !== value) throw new Error(JAVASCRIPT_REJECTED);
    this.index += 1;
    return token;
  }

  private matches(value: string): boolean {
    if (this.peek().value !== value) return false;
    this.index += 1;
    return true;
  }

  private parseConditional(): JavascriptExpression {
    const test = this.parseBinary(0);
    if (!this.matches('?')) return test;
    const consequent = this.parseConditional();
    this.take(':');
    const alternate = this.parseConditional();
    return this.node({ type: 'conditional', test, consequent, alternate });
  }

  private parseBinary(minimumPrecedence: number): JavascriptExpression {
    let left = this.parseUnary();
    const precedence: Record<string, number> = {
      '??': 1,
      '||': 2,
      '&&': 3,
      '==': 4,
      '!=': 4,
      '===': 4,
      '!==': 4,
      '<': 5,
      '<=': 5,
      '>': 5,
      '>=': 5,
      '+': 6,
      '-': 6,
      '*': 7,
      '/': 7,
      '%': 7,
    };
    while (true) {
      const operator = this.peek().value;
      const currentPrecedence = precedence[operator];
      if (currentPrecedence === undefined || currentPrecedence < minimumPrecedence) break;
      this.take();
      const right = this.parseBinary(currentPrecedence + 1);
      left = this.node({ type: 'binary', operator, left, right });
    }
    return left;
  }

  private parseUnary(): JavascriptExpression {
    if (['!', '+', '-'].includes(this.peek().value)) {
      const operator = this.take().value;
      return this.node({ type: 'unary', operator, argument: this.parseUnary() });
    }
    return this.parsePostfix();
  }

  private parsePostfix(): JavascriptExpression {
    let expression = this.parsePrimary();
    while (true) {
      const optional = this.matches('?.');
      if (optional || this.matches('.')) {
        const property = this.take();
        if (property.kind !== 'identifier') throw new Error(JAVASCRIPT_REJECTED);
        expression = this.node({
          type: 'member',
          object: expression,
          property: this.node({ type: 'identifier', name: property.value }),
          computed: false,
          optional,
        });
        continue;
      }
      if (this.matches('[')) {
        const property = this.parseConditional();
        this.take(']');
        expression = this.node({
          type: 'member',
          object: expression,
          property,
          computed: true,
          optional: false,
        });
        continue;
      }
      if (this.matches('(')) {
        const arguments_: JavascriptExpression[] = [];
        if (!this.matches(')')) {
          do {
            arguments_.push(this.parseConditional());
          } while (this.matches(','));
          this.take(')');
        }
        expression = this.node({ type: 'call', callee: expression, arguments: arguments_ });
        continue;
      }
      return expression;
    }
  }

  private parsePrimary(): JavascriptExpression {
    const token = this.take();
    if (token.kind === 'identifier') {
      if (token.value === 'true' || token.value === 'false') {
        return this.node({ type: 'literal', value: token.value === 'true' });
      }
      if (token.value === 'null') return this.node({ type: 'literal', value: null });
      return this.node({ type: 'identifier', name: token.value });
    }
    if (token.kind === 'string') return this.node({ type: 'literal', value: token.value });
    if (token.kind === 'number') return this.node({ type: 'literal', value: Number(token.value) });
    if (token.value === '(') {
      const expression = this.parseConditional();
      this.take(')');
      return expression;
    }
    throw new Error(JAVASCRIPT_REJECTED);
  }
}

type JavascriptValueKind =
  'document' | 'node' | 'collection' | 'string' | 'number' | 'boolean' | 'json' | 'unknown';

const NODE_STRING_PROPERTIES = new Set([
  'textContent',
  'innerText',
  'tagName',
  'id',
  'className',
  'title',
  'ariaLabel',
  'role',
]);
const NODE_NODE_PROPERTIES = new Set([
  'body',
  'head',
  'documentElement',
  'firstElementChild',
  'lastElementChild',
  'parentElement',
  'nextElementSibling',
  'previousElementSibling',
]);
const NODE_NUMBER_PROPERTIES = new Set(['length', 'childElementCount']);
const DOCUMENT_QUERY_METHODS = new Map<string, JavascriptValueKind>([
  ['querySelector', 'node'],
  ['querySelectorAll', 'collection'],
  ['getElementById', 'node'],
  ['getElementsByClassName', 'collection'],
  ['getElementsByTagName', 'collection'],
]);
const NODE_QUERY_METHODS = new Map<string, JavascriptValueKind>([
  ['querySelector', 'node'],
  ['querySelectorAll', 'collection'],
  ['getElementsByClassName', 'collection'],
  ['getElementsByTagName', 'collection'],
  ['closest', 'node'],
  ['matches', 'boolean'],
  ['getAttribute', 'string'],
  ['hasAttribute', 'boolean'],
]);
const STRING_METHODS = new Map<string, JavascriptValueKind>([
  ['trim', 'string'],
  ['toLowerCase', 'string'],
  ['toUpperCase', 'string'],
  ['slice', 'string'],
  ['substring', 'string'],
  ['charAt', 'string'],
  ['includes', 'boolean'],
  ['startsWith', 'boolean'],
  ['endsWith', 'boolean'],
]);

function identifierProperty(expression: JavascriptExpression): string {
  if (expression.type !== 'identifier') throw new Error(JAVASCRIPT_REJECTED);
  return expression.name;
}

function validateJavascriptExpression(expression: JavascriptExpression, depth = 0): JavascriptValueKind {
  if (depth > 20) throw new Error(JAVASCRIPT_REJECTED);
  switch (expression.type) {
    case 'identifier':
      if (expression.name === 'document') return 'document';
      if (expression.name === 'JSON') return 'json';
      throw new Error(JAVASCRIPT_REJECTED);
    case 'literal':
      if (typeof expression.value === 'string') return 'string';
      if (typeof expression.value === 'number') return 'number';
      if (typeof expression.value === 'boolean') return 'boolean';
      return 'unknown';
    case 'unary':
      validateJavascriptExpression(expression.argument, depth + 1);
      return expression.operator === '!' ? 'boolean' : 'number';
    case 'binary': {
      const left = validateJavascriptExpression(expression.left, depth + 1);
      const right = validateJavascriptExpression(expression.right, depth + 1);
      if (['==', '!=', '===', '!==', '<', '<=', '>', '>=', '&&', '||'].includes(expression.operator)) {
        return ['&&', '||'].includes(expression.operator) && left === right ? left : 'boolean';
      }
      if (expression.operator === '??') return left === right ? left : right === 'unknown' ? left : right;
      if (expression.operator === '+' && (left === 'string' || right === 'string')) return 'string';
      return 'number';
    }
    case 'conditional': {
      validateJavascriptExpression(expression.test, depth + 1);
      const consequent = validateJavascriptExpression(expression.consequent, depth + 1);
      const alternate = validateJavascriptExpression(expression.alternate, depth + 1);
      return consequent === alternate ? consequent : 'unknown';
    }
    case 'member': {
      const object = validateJavascriptExpression(expression.object, depth + 1);
      if (expression.computed) {
        if (
          expression.property.type !== 'literal' ||
          typeof expression.property.value !== 'number' ||
          !Number.isSafeInteger(expression.property.value) ||
          expression.property.value < 0 ||
          (object !== 'collection' && object !== 'string')
        ) {
          throw new Error(JAVASCRIPT_REJECTED);
        }
        return object === 'collection' ? 'node' : 'string';
      }
      const property = identifierProperty(expression.property);
      if ((object === 'document' || object === 'node') && NODE_STRING_PROPERTIES.has(property)) {
        return 'string';
      }
      if ((object === 'document' || object === 'node') && NODE_NODE_PROPERTIES.has(property)) {
        return 'node';
      }
      if (
        (object === 'document' || object === 'node' || object === 'collection' || object === 'string') &&
        NODE_NUMBER_PROPERTIES.has(property)
      ) {
        return 'number';
      }
      throw new Error(JAVASCRIPT_REJECTED);
    }
    case 'call': {
      if (expression.callee.type !== 'member' || expression.callee.computed) {
        throw new Error(JAVASCRIPT_REJECTED);
      }
      const object = validateJavascriptExpression(expression.callee.object, depth + 1);
      const method = identifierProperty(expression.callee.property);
      for (const argument of expression.arguments) validateJavascriptExpression(argument, depth + 1);
      if (object === 'json' && method === 'stringify' && expression.arguments.length === 1) return 'string';
      if (object === 'document' && DOCUMENT_QUERY_METHODS.has(method)) {
        if (expression.arguments.length !== 1 || expression.arguments[0]?.type !== 'literal') {
          throw new Error(JAVASCRIPT_REJECTED);
        }
        return DOCUMENT_QUERY_METHODS.get(method)!;
      }
      if (object === 'node' && NODE_QUERY_METHODS.has(method)) {
        if (expression.arguments.length !== 1 || expression.arguments[0]?.type !== 'literal') {
          throw new Error(JAVASCRIPT_REJECTED);
        }
        return NODE_QUERY_METHODS.get(method)!;
      }
      if (object === 'collection' && method === 'item') {
        if (expression.arguments.length !== 1) throw new Error(JAVASCRIPT_REJECTED);
        return 'node';
      }
      if (object === 'string' && STRING_METHODS.has(method)) {
        if (expression.arguments.length > 2) throw new Error(JAVASCRIPT_REJECTED);
        return STRING_METHODS.get(method)!;
      }
      throw new Error(JAVASCRIPT_REJECTED);
    }
  }
}

export function compileV3BrowserJavascriptReadOnly(source: string): V3BrowserJavascriptExpression {
  try {
    if (typeof source !== 'string' || !source.trim() || source.length > 4_096 || source.includes('\0')) {
      throw new Error(JAVASCRIPT_REJECTED);
    }
    const expression = new ReadOnlyJavascriptParser(tokenizeJavascript(source)).parse();
    validateJavascriptExpression(expression);
    return expression;
  } catch {
    throw new Error(JAVASCRIPT_REJECTED);
  }
}

export function assertV3BrowserJavascriptReadOnly(source: string): void {
  void compileV3BrowserJavascriptReadOnly(source);
}

function makeTool<T extends TSchema>(
  name: string,
  label: string,
  description: string,
  parameters: T,
  execute: ToolDefinition<T>['execute'],
): ToolDefinition<T> {
  return { name, label, description, parameters, executionMode: 'sequential', execute };
}

export async function loadV3BrowserConnectorTools(
  options: LoadV3BrowserConnectorToolsOptions,
): Promise<ToolDefinition[]> {
  if (options.subjectType !== 'waker' || !options.host) return [];
  const hostOptions = { ...options, host: options.host };
  const deadlineMs = deadline(options);
  const initial = await currentState(hostOptions, undefined, deadlineMs).catch(() => undefined);
  if (!initial) return [];
  if (!initial.browserContextToolAvailable) return [];

  const context = makeTool(
    CONTEXT_TOOL,
    'Browser context',
    'Read only the currently host-authorized Browser page context. Never enumerates ordinary tabs.',
    ContextParameters,
    async (_toolCallId, rawParameters, signal) => {
      const parameters = checkedParameters(ContextParameters, rawParameters);
      if (!parameters) return failure(INVALID_INPUT);
      const latest = await currentState(hostOptions, signal, deadlineMs);
      if (!latest.browserContextToolAvailable) return failure(BROWSER_TOOL_UNAVAILABLE);
      if (!latest.browserPageToolReady) return completed(V3_BROWSER_CONTEXT_EMPTY_RESULT);
      return dispatch(hostOptions, 'tabs_context_mcp', {}, signal, deadlineMs, 50_000);
    },
  );
  if (!initial.browserPageToolReady) return [context];

  const readPage = makeTool(
    READ_PAGE_TOOL,
    'Read page',
    'Read a bounded accessibility-tree view of the host-authorized page without changing it.',
    ReadPageParameters,
    async (_toolCallId, rawParameters, signal) => {
      const parameters = checkedParameters(ReadPageParameters, rawParameters);
      if (!parameters) return failure(INVALID_INPUT);
      const latest = await currentState(hostOptions, signal, deadlineMs);
      if (!latest.browserPageToolReady) return failure(BROWSER_PAGE_UNAVAILABLE);
      return dispatch(
        hostOptions,
        'read_page',
        parameters,
        signal,
        deadlineMs,
        parameters.max_chars ?? 50_000,
      );
    },
  );
  const getPageText = makeTool(
    GET_PAGE_TEXT_TOOL,
    'Get page text',
    'Extract bounded visible text from the same host-authorized page without changing it.',
    GetPageTextParameters,
    async (_toolCallId, rawParameters, signal) => {
      const parameters = checkedParameters(GetPageTextParameters, rawParameters);
      if (!parameters) return failure(INVALID_INPUT);
      const latest = await currentState(hostOptions, signal, deadlineMs);
      if (!latest.browserPageToolReady) return failure(BROWSER_PAGE_UNAVAILABLE);
      return dispatch(
        hostOptions,
        'get_page_text',
        parameters,
        signal,
        deadlineMs,
        parameters.max_chars ?? 50_000,
      );
    },
  );
  const javascript = makeTool(
    JAVASCRIPT_TOOL,
    'Read page with JavaScript',
    'Evaluate one parser-validated, bounded, read-only expression on the host-authorized page.',
    JavascriptParameters,
    async (_toolCallId, rawParameters, signal) => {
      const parameters = checkedParameters(JavascriptParameters, rawParameters);
      if (!parameters) return failure(INVALID_INPUT);
      try {
        assertV3BrowserJavascriptReadOnly(parameters.text);
      } catch {
        return failure(JAVASCRIPT_REJECTED);
      }
      const latest = await currentState(hostOptions, signal, deadlineMs);
      if (!latest.browserPageToolReady) return failure(BROWSER_PAGE_UNAVAILABLE);
      return dispatch(hostOptions, 'javascript_tool', parameters, signal, deadlineMs, 50_000);
    },
  );
  return [context, readPage, getPageText, javascript];
}
