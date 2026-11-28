// Tests of the external converter, without hardware: synthetic Tuya frames decoded through the
// definition as Zigbee2MQTT prepares it. Run with `npm test` (node:test).

"use strict";

const assert = require("node:assert/strict");
const {test, beforeEach} = require("node:test");

const zhc = require("zigbee-herdsman-converters");
const definition = require("../tuya_pilot_wire_fu1bfwza.js");

const {decode, faults, transitions, scheduleParts, MODE_BY_INDEX} = definition._internals;

const IEEE = "0xa4c1380000000001";

// Tuya data point frames, as zigbee-herdsman hands them over.
const number = (dp, value) => {
    const data = Buffer.alloc(4);
    data.writeInt32BE(value);
    return {dp, datatype: 2, data};
};
const bool = (dp, value) => ({dp, datatype: 1, data: Buffer.from([value ? 1 : 0])});
const enumeration = (dp, index) => ({dp, datatype: 4, data: Buffer.from([index])});
const bitmap = (dp, value) => ({dp, datatype: 5, data: Buffer.from([value])});
const raw = (dp, bytes) => ({dp, datatype: 0, data: Buffer.from(bytes)});

function part(header, setpoints) {
    return [...Array(12).fill(header), ...setpoints.map((t) => t * 2)];
}

let sequence = 0;

function mockDevice() {
    return {
        ieeeAddr: IEEE,
        modelID: "TS0601",
        manufacturerName: "_TZE204_fu1bfwza",
        type: "Router",
        powerSource: "Mains (single phase)",
        endpoints: [{ID: 1, inputClusters: [0, 4, 5, 61184], outputClusters: [25, 10], getInputClusters: () => [], getOutputClusters: () => []}],
        getEndpoint: () => undefined,
        customClusters: {},
        meta: {},
        save: () => {},
        addCustomCluster: () => {},
    };
}

/** Run the definition's fromZigbee converters on one frame, as Zigbee2MQTT does. */
function receive(prepared, dpValues, state = {}) {
    const msg = {
        cluster: "manuSpecificTuya",
        type: "commandDataReport",
        data: {dpValues, seq: sequence},
        device: mockDevice(),
        endpoint: {ID: 1, command: async () => {}},
        meta: {zclTransactionSequenceNumber: sequence++},
    };
    const payload = {};
    for (const converter of prepared.fromZigbee) {
        if (converter.cluster !== msg.cluster) continue;
        if (!(Array.isArray(converter.type) ? converter.type : [converter.type]).includes(msg.type)) continue;
        Object.assign(payload, converter.convert(prepared, msg, () => {}, {}, {state, device: msg.device, logger: console}) ?? {});
    }
    return payload;
}

beforeEach(() => scheduleParts.clear());

test("Zigbee2MQTT recognises the thermostat by its fingerprint", async () => {
    zhc.addExternalDefinition(definition);
    try {
        const found = await zhc.findByDevice(mockDevice());
        assert.equal(found?.model, "TS0601_fu1bfwza");
        assert.equal(found.vendor, "Tuya");
        const other = await zhc.findByDevice({...mockDevice(), manufacturerName: "_TZE204_3regm3h6"});
        assert.notEqual(other?.model, "TS0601_fu1bfwza");
    } finally {
        zhc.removeExternalDefinitions();
    }
});

test("a full report decodes to the contract's property names", () => {
    const prepared = zhc.prepareDefinition(definition);
    const payload = receive(prepared, [
        bool(1, true),
        number(16, 195),
        enumeration(17, 0),
        number(19, -2),
        bitmap(20, 0),
        number(24, 120),
        bool(29, true),
        bool(39, false),
        number(50, 205),
        number(101, 2302),
        number(102, 4350),
        number(103, 5),
        number(107, 10055),
        number(116, 70),
        number(117, 170),
    ]);
    assert.deepEqual(payload, {
        system_mode: "heat",
        local_temperature: 19.5,
        window_open: false,
        local_temperature_calibration: -2,
        fault: [],
        holiday_temperature: 12,
        window_detection: "ON",
        child_lock: "UNLOCK",
        current_heating_setpoint: 20.5,
        voltage: 230.2,
        current: 4.35,
        temperature_sensibility: 0.5,
        energy: 1005.5,
        antifrost_temperature: 7,
        eco_temperature: 17,
        running_state: "heat",
        power: 1001.4,
    });
});

test("off, open window, child lock", () => {
    assert.deepEqual(decode([bool(1, false), enumeration(17, 1), bool(29, false), bool(39, true)]), {
        system_mode: "off",
        window_open: true,
        window_detection: "OFF",
        child_lock: "LOCK",
    });
});

test("running state and power come from the current", () => {
    assert.deepEqual(decode([number(102, 0)]), {current: 0, running_state: "idle", power: 0});
    // Voltage from an earlier frame, current in this one.
    assert.deepEqual(decode([number(102, 1000)], {voltage: 230}), {current: 1, running_state: "heat", power: 230});
    // No voltage known: no power, rather than a guess.
    assert.deepEqual(decode([number(102, 1000)]), {current: 1, running_state: "heat"});
});

test("the mode is published raw while its index table is not established", () => {
    assert.deepEqual(MODE_BY_INDEX, {});
    for (const index of [0, 1, 2, 3, 4, 5, 6, 7]) {
        assert.deepEqual(decode([enumeration(2, index)]), {mode_index: index});
    }
    // And the load state likewise: no running_state from DP 124 alone.
    assert.deepEqual(decode([enumeration(124, 1)]), {work_state_index: 1});
});

test("a filled index table gives the preset", (t) => {
    t.after(() => delete MODE_BY_INDEX[3]);
    MODE_BY_INDEX[3] = "manual";
    assert.deepEqual(decode([enumeration(2, 3)]), {mode_index: 3, preset: "manual"});
    assert.deepEqual(decode([enumeration(2, 4)]), {mode_index: 4});
});

test("fault bitmap to the declared labels", () => {
    assert.deepEqual(faults(0), []);
    assert.deepEqual(faults(0b101), ["e1", "e3"]);
    assert.deepEqual(faults(0b1000), ["bit_3"]);
    assert.equal(faults("x"), undefined);
    assert.deepEqual(decode([bitmap(20, 2)]), {fault: ["e2"]});
});

test("unknown data points and wrong types are dropped", () => {
    assert.deepEqual(decode([number(99, 1), number(11, 0), number(120, 1)]), {});
    assert.deepEqual(decode([enumeration(17, 7)]), {});
    assert.deepEqual(decode([{dp: 16, datatype: 3, data: Buffer.from("19")}]), {});
    assert.deepEqual(decode([{dp: 1, datatype: 2, data: Buffer.from([0, 0, 0, 1])}]), {});
});

test("weekly schedule: a day is published once its four parts are known", () => {
    const night = Array(24).fill(16);
    const morning = [...Array(24).fill(16)];
    morning[2] = 19; // 06:30 in the second part
    for (let i = 3; i < 24; i++) morning[i] = 19;
    // Monday is DP 125-128, header 0x11; Tuesday DP 129-132, header 0x55.
    assert.deepEqual(decode([raw(125, part(0x11, night))], {}, IEEE), {});
    assert.deepEqual(decode([raw(126, part(0x11, morning)), raw(127, part(0x11, Array(24).fill(19)))], {}, IEEE), {});
    const monday = decode([raw(128, part(0x11, [...Array(20).fill(19), ...Array(4).fill(16)]))], {}, IEEE);
    assert.deepEqual(monday, {schedule_monday: "00:00/16 06:30/19 23:00/16"});
    // Another device's parts are its own.
    assert.deepEqual(decode([raw(128, part(0x11, night))], {}, "0xother"), {});
    // A malformed part is ignored.
    assert.deepEqual(decode([raw(129, [1, 2, 3])], {}, IEEE), {});
    const sunday = [153 - 4, 150, 151, 152].map((dp) => raw(dp, part(0x11, Array(24).fill(17.5))));
    assert.deepEqual(decode(sunday, {}, IEEE), {schedule_sunday: "00:00/17.5"});
});

test("transitions are on the 15-minute step", () => {
    const day = Array(96).fill(16);
    day.fill(20.5, 7 * 4 + 1, 22 * 4);
    assert.equal(transitions(day), "00:00/16 07:15/20.5 22:00/16");
});

test("nothing can be written: no toZigbee converter, every key read only", () => {
    const prepared = zhc.prepareDefinition(definition);
    const own = prepared.toZigbee.flatMap((converter) => converter.key);
    for (const key of ["current_heating_setpoint", "preset", "system_mode", "child_lock", "window_detection", "local_temperature_calibration", "schedule_monday"]) {
        assert.ok(!own.includes(key), `${key} has a toZigbee converter`);
    }
    const features = (expose) => [expose, ...(expose.features ?? []).flatMap(features)];
    const settable = prepared.exposes
        .flatMap(features)
        .filter((expose) => expose.property && (expose.access & zhc.access.SET) !== 0)
        .map((expose) => expose.property);
    assert.deepEqual(settable, []);
});
