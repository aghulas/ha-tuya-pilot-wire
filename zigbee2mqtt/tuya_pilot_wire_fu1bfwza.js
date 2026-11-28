/**
 * Zigbee2MQTT external converter: Tuya "FP Thermostat", pilot-wire thermostat for electric
 * radiators, `TS0601` / `_TZE204_fu1bfwza` (Tuya product id `fu1bfwza`, category `wk`).
 *
 * Part of https://github.com/aghulas/ha-tuya-pilot-wire (milestone M5). Format: external
 * converter of Zigbee2MQTT 2.x (CommonJS), tested against zigbee-herdsman-converters 26.x.
 *
 * READ ONLY BY CONSTRUCTION. No data point has a `to` conversion and the definition has no
 * `toZigbee` converter: Zigbee2MQTT answers every `/set` with "no converter", and nothing is
 * written to the device. A write is added here only after it has been proven on real hardware
 * through Zigbee2MQTT (supervised trial, read back from an independent source), one key at a time.
 * The only frames the definition sends are Tuya's standard ones: the time the device asks for
 * (`mcuSyncTime`) and the configure sequence of `tuyaBase`.
 *
 * Property names are those of the MQTT contract of `tuyapilot2mqtt` (the Zigbee2MQTT dialect),
 * so that the Companion sees the same thermostat on either bridge. Data points: the table of
 * `pytuya-pilot-wire` (`dps.py`), the same numbers on both networks.
 *
 * Not established yet, measured on site (docs/z2m-trial-procedure.md):
 * - the enum index of each mode on DP 2 (`MODE_BY_INDEX` is empty until then: `preset` is not
 *   published, the raw index is, as `mode_index`);
 * - the enum index of each load state on DP 124 (`running_state` comes from the current, DP 102);
 * - whether the device reports its weekly schedule (DP 125-152) over Zigbee at all.
 */

"use strict";

const tuya = require("zigbee-herdsman-converters/lib/tuya");
const exposes = require("zigbee-herdsman-converters/lib/exposes");

const e = exposes.presets;
const ea = exposes.access;

const PRODUCT_ID = "fu1bfwza";
const MANUFACTURER_NAMES = ["_TZE204_fu1bfwza", "_TZE284_fu1bfwza"];

const PRESETS = ["program", "manual", "eco", "holiday", "antifrost"];

// DP 2 enum index -> contract preset. EMPTY ON PURPOSE: the cloud's declared list (eco, holiday,
// program, manual, plus an undeclared frost-protection value) does not tell the Zigbee index, and
// a public converter saw indices 0, 1, 2, 4 and 5 on its unit. Filled from the on-site
// measurement, one index per mode, never guessed.
const MODE_BY_INDEX = {};

// DP 124 enum index -> heating. Empty for the same reason; DP 102 (current) decides meanwhile.
const HEATING_BY_WORK_STATE_INDEX = {};

// DP 17 `window_state`, declared `close` / `open`: the index follows the declared order.
const WINDOW_BY_INDEX = {0: false, 1: true};

// DP 20 `fault` bitmap: the labels the device declares, bit 0 first.
const FAULT_LABELS = ["e1", "e2", "e3"];

const DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"];
const SCHEDULE_FIRST_DP = 125; // week_program_18_<day>_<part>: 125 + (day - 1) * 4 + (part - 1)
const SCHEDULE_HEADER_BYTES = 12;
const SCHEDULE_PART_SETPOINTS = 24; // 6 h at a 15-minute step
const SCHEDULE_PART_BYTES = SCHEDULE_HEADER_BYTES + SCHEDULE_PART_SETPOINTS;

const round = (value, digits) => {
    const factor = 10 ** digits;
    return Math.round(value * factor) / factor;
};

const isNumber = (value) => typeof value === "number" && Number.isFinite(value);

const divideBy = (divisor) => (value) => (isNumber(value) ? round(value / divisor, 3) : undefined);

const lookup = (table) => (value) => (Object.hasOwn(table, value) ? table[value] : undefined);

const onOff = (on, off) => (value) => (typeof value === "boolean" ? (value ? on : off) : undefined);

function faults(bitmap) {
    if (!isNumber(bitmap) || bitmap < 0) return undefined;
    const names = [];
    for (let bit = 0; 2 ** bit <= bitmap; bit++) {
        if (Math.floor(bitmap / 2 ** bit) % 2 === 1) names.push(FAULT_LABELS[bit] ?? `bit_${bit}`);
    }
    return names;
}

/** One day's 96 setpoints (°C) to "HH:MM/T HH:MM/T ...", one entry per change. */
function transitions(setpoints) {
    const out = [];
    let previous;
    setpoints.forEach((temperature, index) => {
        if (temperature !== previous) {
            const minutes = index * 15;
            const hh = String(Math.floor(minutes / 60)).padStart(2, "0");
            const mm = String(minutes % 60).padStart(2, "0");
            out.push(`${hh}:${mm}/${temperature}`);
            previous = temperature;
        }
    });
    return out.join(" ");
}

/** The 24 setpoints of one schedule part (36 raw bytes), or undefined when malformed. */
function schedulePart(raw) {
    if (!raw || raw.length !== SCHEDULE_PART_BYTES) return undefined;
    return Array.from(raw.subarray(SCHEDULE_HEADER_BYTES), (byte) => byte / 2);
}

// The parts of the schedule seen so far, per device: a day is published only once its four
// parts are known. Kept in memory only; after a restart the day waits for the device's next
// report of it, rather than showing a mix of old and new parts.
const scheduleParts = new Map();

// Data point -> [contract property, conversion]. Only these are read; any other DP is ignored.
const DATAPOINTS = {
    1: ["system_mode", onOff("heat", "off")],
    2: ["mode_index", (value) => (isNumber(value) ? value : undefined)],
    16: ["local_temperature", divideBy(10)],
    17: ["window_open", lookup(WINDOW_BY_INDEX)],
    19: ["local_temperature_calibration", (value) => (Number.isInteger(value) ? value : undefined)],
    20: ["fault", faults],
    24: ["holiday_temperature", divideBy(10)],
    29: ["window_detection", onOff("ON", "OFF")],
    39: ["child_lock", onOff("LOCK", "UNLOCK")],
    50: ["current_heating_setpoint", divideBy(10)],
    101: ["voltage", divideBy(10)],
    102: ["current", divideBy(1000)],
    103: ["temperature_sensibility", divideBy(10)],
    107: ["energy", divideBy(10)],
    116: ["antifrost_temperature", divideBy(10)],
    117: ["eco_temperature", divideBy(10)],
    124: ["work_state_index", (value) => (isNumber(value) ? value : undefined)],
};

/**
 * Decode the data points of one Tuya frame into contract properties.
 *
 * `previous` is the state Zigbee2MQTT holds for the device (for the voltage, which can come in an
 * earlier frame than the current). A value of the wrong type is dropped, never defaulted.
 */
function decode(dpValues, previous = {}, ieeeAddr = "") {
    const result = {};
    for (const dpValue of dpValues) {
        const dp = dpValue.dp;
        const value = tuya.getDataValue(dpValue);
        if (dp >= SCHEDULE_FIRST_DP && dp < SCHEDULE_FIRST_DP + DAYS.length * 4) {
            const setpoints = schedulePart(Buffer.isBuffer(value) ? value : Buffer.from(value ?? []));
            if (setpoints === undefined) continue;
            const offset = dp - SCHEDULE_FIRST_DP;
            const day = DAYS[Math.floor(offset / 4)];
            const parts = scheduleParts.get(ieeeAddr) ?? {};
            parts[day] = parts[day] ?? [undefined, undefined, undefined, undefined];
            parts[day][offset % 4] = setpoints;
            scheduleParts.set(ieeeAddr, parts);
            if (parts[day].every((part) => part !== undefined)) {
                result[`schedule_${day}`] = transitions(parts[day].flat());
            }
            continue;
        }
        const entry = DATAPOINTS[dp];
        if (!entry) continue;
        const [property, convert] = entry;
        const converted = convert(value);
        if (converted !== undefined) result[property] = converted;
    }

    if ("mode_index" in result) {
        const preset = MODE_BY_INDEX[result.mode_index];
        if (preset !== undefined) result.preset = preset;
    }
    if ("current" in result) {
        result.running_state = result.current > 0 ? "heat" : "idle";
        const voltage = "voltage" in result ? result.voltage : previous.voltage;
        if (result.current === 0) result.power = 0;
        else if (isNumber(voltage)) result.power = round(voltage * result.current, 1);
    } else if ("work_state_index" in result) {
        const heating = HEATING_BY_WORK_STATE_INDEX[result.work_state_index];
        if (heating !== undefined) result.running_state = heating ? "heat" : "idle";
    }
    return result;
}

const fzDatapoints = {
    cluster: "manuSpecificTuya",
    type: ["commandDataResponse", "commandDataReport", "commandActiveStatusReport", "commandActiveStatusReportAlt"],
    convert: (model, msg, publish, options, meta) => {
        const dpValues = msg.data?.dpValues;
        if (!Array.isArray(dpValues)) return;
        return decode(dpValues, meta?.state ?? {}, msg.device?.ieeeAddr ?? "");
    },
};

const definition = {
    fingerprint: tuya.fingerprint("TS0601", MANUFACTURER_NAMES),
    model: `TS0601_${PRODUCT_ID}`,
    vendor: "Tuya",
    description: "Pilot-wire thermostat for electric radiators (FP Thermostat), read only",
    extend: [tuya.modernExtend.tuyaBase({timeStart: "1970"})],
    fromZigbee: [fzDatapoints],
    toZigbee: [],
    exposes: [
        e
            .climate()
            .withSetpoint("current_heating_setpoint", 5, 40, 0.5, ea.STATE)
            .withLocalTemperature(ea.STATE)
            .withLocalTemperatureCalibration(-9, 9, 1, ea.STATE)
            .withSystemMode(["off", "heat"], ea.STATE)
            .withRunningState(["idle", "heat"], ea.STATE),
        e.enum("preset", ea.STATE, PRESETS).withDescription("Running mode (absent while its index is not established)"),
        e.numeric("mode_index", ea.STATE).withDescription("Raw enum index of the mode data point (DP 2)").withCategory("diagnostic"),
        e.numeric("work_state_index", ea.STATE).withDescription("Raw enum index of the load state (DP 124)").withCategory("diagnostic"),
        e.binary("window_open", ea.STATE, true, false).withDescription("Open window detected"),
        e.binary("window_detection", ea.STATE, "ON", "OFF").withDescription("Open-window detection enabled"),
        e.binary("child_lock", ea.STATE, "LOCK", "UNLOCK").withDescription("Child lock"),
        e.numeric("holiday_temperature", ea.STATE).withUnit("°C").withDescription("Setpoint of the holiday mode"),
        e.numeric("eco_temperature", ea.STATE).withUnit("°C").withDescription("Setpoint of the eco mode"),
        e.numeric("antifrost_temperature", ea.STATE).withUnit("°C").withDescription("Setpoint of the frost-protection mode"),
        e.numeric("temperature_sensibility", ea.STATE).withUnit("°C").withDescription("Regulation hysteresis"),
        e.list("fault", ea.STATE, e.text("fault", ea.STATE)).withDescription("Active faults, empty when none"),
        e.power(),
        e.voltage(),
        e.current(),
        e.energy(),
        ...DAYS.map((day) =>
            e.text(`schedule_${day}`, ea.STATE).withDescription(`Weekly schedule, ${day}: "HH:MM/°C" at each change`),
        ),
    ],
};

module.exports = definition;
// For the tests; Zigbee2MQTT reads only the definition.
Object.defineProperty(module.exports, "_internals", {
    enumerable: false,
    value: {decode, faults, transitions, scheduleParts, DATAPOINTS, MODE_BY_INDEX, MANUFACTURER_NAMES},
});
