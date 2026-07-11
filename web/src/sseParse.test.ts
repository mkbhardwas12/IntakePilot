import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { parseFrame } from "./sseParse.ts";

describe("parseFrame", () => {
  it("parses event and data lines", () => {
    const { event, data } = parseFrame('event: decision\ndata: {"slot":"priority"}\n');
    assert.equal(event, "decision");
    assert.deepEqual(JSON.parse(data), { slot: "priority" });
  });

  it("concatenates multi-line data", () => {
    const { event, data } = parseFrame('event: done\ndata: {"a":1,\ndata: "b":2}\n');
    assert.equal(event, "done");
    assert.equal(data, '{"a":1,\n"b":2}');
  });

  it("defaults event to message", () => {
    const { event, data } = parseFrame('data: {"ok":true}');
    assert.equal(event, "message");
    assert.equal(data, '{"ok":true}');
  });

  it("strips CR from lines", () => {
    const { event } = parseFrame("event: status\r\ndata: {}\r\n");
    assert.equal(event, "status");
  });
});
