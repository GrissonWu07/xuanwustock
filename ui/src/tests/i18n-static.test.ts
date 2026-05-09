// @ts-nocheck
import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import process from "node:process";
import ts from "typescript";

const SRC_ROOT = join(process.cwd(), "src");
const HAN_RE = /[\u4e00-\u9fff]/;

const EXCLUDED_PARTS = new Set(["locales", "tests"]);
const SOURCE_EXTENSIONS = new Set([".ts", ".tsx"]);

const hasSourceExtension = (filePath: string) => {
  for (const extension of SOURCE_EXTENSIONS) {
    if (filePath.endsWith(extension)) return true;
  }
  return false;
};

const shouldSkip = (filePath: string) => {
  const parts = relative(SRC_ROOT, filePath).split(/[\\/]/);
  return parts.some((part) => EXCLUDED_PARTS.has(part));
};

const collectSourceFiles = (root: string): string[] => {
  const entries = readdirSync(root);
  return entries.flatMap((entry) => {
    const fullPath = join(root, entry);
    const stat = statSync(fullPath);
    if (stat.isDirectory()) {
      return shouldSkip(fullPath) ? [] : collectSourceFiles(fullPath);
    }
    return hasSourceExtension(fullPath) && !shouldSkip(fullPath) ? [fullPath] : [];
  });
};

const hasExplicitLocaleBranch = (line: string) =>
  line.includes('locale === "zh-CN"') || line.includes("locale === 'zh-CN'") || /\bzh\s*:\s*["'`]/.test(line);

const isNonUiParsingLine = (line: string) => {
  const trimmed = line.trim();
  if (/^["'`][^"'`]*[\u4e00-\u9fff][^"'`]*["'`]\s*:/.test(trimmed)) return true;
  if (/\/.+[\u4e00-\u9fff].+\/[a-z]*/.test(line)) return true;
  if (line.includes(".includes(") && HAN_RE.test(line)) return true;
  return false;
};

const isInsideTCall = (node: ts.Node) => {
  let current: ts.Node | undefined = node.parent;
  while (current) {
    if (ts.isCallExpression(current) && ts.isIdentifier(current.expression) && current.expression.text === "t") {
      return true;
    }
    current = current.parent;
  }
  return false;
};

const isPropertyName = (node: ts.Node) => {
  const parent = node.parent;
  return Boolean(parent && ts.isPropertyAssignment(parent) && parent.name === node);
};

const lineFor = (source: string, position: number) => {
  const start = source.lastIndexOf("\n", position) + 1;
  const end = source.indexOf("\n", position);
  return source.slice(start, end < 0 ? source.length : end);
};

describe("static UI i18n coverage", () => {
  it("does not leave Chinese UI literals outside i18n calls", () => {
    const offenders: string[] = [];
    const files = collectSourceFiles(SRC_ROOT);

    for (const filePath of files) {
      const relativePath = relative(SRC_ROOT, filePath).replace(/\\/g, "/");
      const source = readFileSync(filePath, "utf8");
      const sourceFile = ts.createSourceFile(
        filePath,
        source,
        ts.ScriptTarget.Latest,
        true,
        filePath.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
      );

      const checkNode = (node: ts.Node) => {
        const text = ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) ? node.text : node.getText(sourceFile);
        if (!HAN_RE.test(text)) return;
        const position = node.getStart(sourceFile);
        const line = lineFor(source, position);
        const lineNumber = sourceFile.getLineAndCharacterOfPosition(position).line + 1;
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("//") || trimmed.startsWith("*")) return;
        if (hasExplicitLocaleBranch(line)) return;
        if (isNonUiParsingLine(line)) return;
        if (isInsideTCall(node)) return;
        if (isPropertyName(node)) return;
        offenders.push(`${relativePath}:${lineNumber}: ${trimmed}`);
      };

      const visit = (node: ts.Node) => {
        if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateExpression(node) || ts.isJsxText(node)) {
          checkNode(node);
        }
        ts.forEachChild(node, visit);
      };

      visit(sourceFile);
    }

    expect(offenders).toEqual([]);
  });
});
