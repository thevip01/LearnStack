import { test } from "node:test";
import assert from "node:assert/strict";
import { LUCIDE_GLYPHS, monogram, resolveGlyph } from "./glyph.ts";

test("a known brand name wins over everything else", () => {
  assert.deepEqual(resolveGlyph("python", "Python"), { kind: "brand", mark: "python" });
  assert.deepEqual(resolveGlyph("PYTHON", "Python"), { kind: "brand", mark: "python" });
  assert.deepEqual(resolveGlyph(" Py ", "Python"), { kind: "brand", mark: "python" });
  assert.deepEqual(resolveGlyph("node.js", "Backend"), { kind: "brand", mark: "javascript" });
});

test("the names this repo's packages actually declare all resolve", () => {
  // subjects/programming/python: theme icon, domain icon, four module icons.
  assert.deepEqual(resolveGlyph("python", "Python"), { kind: "brand", mark: "python" });
  assert.deepEqual(resolveGlyph("code", "Programming"), { kind: "lucide", name: "code" });
  assert.deepEqual(resolveGlyph("box", "Objects"), { kind: "lucide", name: "box" });
  assert.deepEqual(resolveGlyph("function", "Functions"), { kind: "lucide", name: "braces" });
  assert.deepEqual(resolveGlyph("layers", "Data model"), { kind: "lucide", name: "layers" });
  assert.deepEqual(resolveGlyph("gauge", "Performance"), { kind: "lucide", name: "gauge" });
});

test("an alias resolves to the icon it means", () => {
  assert.deepEqual(resolveGlyph("kubernetes", "Platform"), { kind: "lucide", name: "boxes" });
  assert.deepEqual(resolveGlyph("k8s", "Platform"), { kind: "lucide", name: "boxes" });
  assert.deepEqual(resolveGlyph("postgresql", "Databases"), { kind: "lucide", name: "database" });
  assert.deepEqual(resolveGlyph("machine-learning", "Machine Learning"), { kind: "monogram", text: "ML" });
  assert.deepEqual(resolveGlyph("ml", "Machine Learning"), { kind: "lucide", name: "brain" });
});

test("a URL is refused rather than loaded", () => {
  // One of the source records in this repo carries exactly this value.
  assert.deepEqual(resolveGlyph("https://lodash.com/icon.svg", "Lodash"), { kind: "monogram", text: "Lo" });
  assert.deepEqual(resolveGlyph("/static/aws.png", "Amazon Web Services"), { kind: "monogram", text: "AW" });
});

test("an unknown name falls back to initials, not to a generic icon", () => {
  assert.deepEqual(resolveGlyph("wobbledy", "Rust Systems"), { kind: "monogram", text: "RS" });
  assert.deepEqual(resolveGlyph(null, "Python"), { kind: "monogram", text: "Py" });
  assert.deepEqual(resolveGlyph(undefined, "Python"), { kind: "monogram", text: "Py" });
  assert.deepEqual(resolveGlyph("   ", "Python"), { kind: "monogram", text: "Py" });
});

test("monogram takes two words, or two letters from one", () => {
  assert.equal(monogram("Modern Python"), "MP");
  assert.equal(monogram("Python"), "Py");
  assert.equal(monogram("Distributed Systems Design"), "DS");
  assert.equal(monogram("aws"), "Aw");
});

test("monogram skips words that carry no identity", () => {
  assert.equal(monogram("The Art of Testing"), "AT");
  assert.equal(monogram("Introduction to SQL"), "IS");
  // Every word is noise, so the rule gives way rather than returning nothing.
  assert.equal(monogram("The And"), "TA");
});

test("monogram survives punctuation, digits and emptiness", () => {
  assert.equal(monogram("C++"), "C");
  assert.equal(monogram("3D Graphics"), "3G");
  assert.equal(monogram("  "), "?");
  assert.equal(monogram("!!!"), "?");
});

test("every lucide glyph name is unique and lowercase", () => {
  assert.equal(new Set(LUCIDE_GLYPHS).size, LUCIDE_GLYPHS.length);
  for (const name of LUCIDE_GLYPHS) {
    assert.equal(name, name.toLowerCase(), `${name} should be lowercase`);
  }
});
