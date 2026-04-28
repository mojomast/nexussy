import { expect, test } from "bun:test";
import { getAnchorBlock, listAnchors, setAnchorBlock } from "../src/lib/anchors";

const doc = "before\n<!-- FOO_START -->\none\n<!-- FOO_END -->\nmiddle\n<!-- BAR_START -->\ntwo\n<!-- BAR_END -->\nafter";

test("getAnchorBlock returns correct content for a known anchor", () => {
  expect(getAnchorBlock(doc, "foo").trim()).toBe("one");
});

test("getAnchorBlock returns empty string when anchor is absent", () => {
  expect(getAnchorBlock(doc, "MISSING")).toBe("");
});

test("setAnchorBlock replaces only target block", () => {
  const next = setAnchorBlock(doc, "FOO", "new");
  expect(getAnchorBlock(next, "FOO").trim()).toBe("new");
  expect(getAnchorBlock(next, "BAR").trim()).toBe("two");
  expect(next).toContain("before");
  expect(next).toContain("after");
});

test("setAnchorBlock handles CRLF line endings", () => {
  const crlf = "<!-- FOO_START -->\r\none\r\n<!-- FOO_END -->\r\n";
  const next = setAnchorBlock(crlf, "foo", "two");
  expect(next).toContain("<!-- FOO_START -->\r\ntwo\r\n<!-- FOO_END -->");
});

test("listAnchors returns all anchor names", () => {
  expect(listAnchors(doc)).toEqual(["FOO", "BAR"]);
});

test("setAnchorBlock throws when START exists but END is missing", () => {
  expect(() => setAnchorBlock("<!-- FOO_START -->\none", "FOO", "two")).toThrow("missing END");
});
