// pslib.jsx - Photoshop building blocks for psagent.
//
// The planner (a local LLM) only ever chooses from the operations in OPS and
// FINISH below and sets their parameters; this file does the actual work.
// ExtendScript is ES3: no let/const, arrow functions or JSON object.
// Every radius is in pixels at the working size (default 3000 px long edge).

var PSLOG = [];
function note(m) { PSLOG.push(String(m)); }

function cid(s) { return charIDToTypeID(s); }
function sid(s) { return stringIDToTypeID(s); }

function num(v, lo, hi, d) {
    if (v === undefined || v === null || isNaN(Number(v))) { v = d; }
    v = Number(v);
    if (v < lo) { v = lo; }
    if (v > hi) { v = hi; }
    return v;
}

function colourOf(hex, fallback) {
    var h = String(hex || fallback).replace("#", "");
    if (!/^[0-9a-fA-F]{6}$/.test(h)) { h = String(fallback).replace("#", ""); }
    var c = new SolidColor();
    c.rgb.hexValue = h.toUpperCase();
    return c;
}

// ------------------------------------------------------------ layer helpers

function dupAbove(doc, layer, name) {
    var d = layer.duplicate(layer, ElementPlacement.PLACEBEFORE);
    if (name) { d.name = name; }
    doc.activeLayer = d;
    return d;
}

function mergeDown(doc, layer) {
    doc.activeLayer = layer;
    var m = layer.merge();
    doc.activeLayer = m;
    return m;
}

function fillLayerAbove(doc, layer, colour, mode, opacity) {
    doc.activeLayer = layer;
    var f = doc.artLayers.add();
    f.move(layer, ElementPlacement.PLACEBEFORE);
    doc.activeLayer = f;
    doc.selection.selectAll();
    doc.selection.fill(colour);
    doc.selection.deselect();
    f.blendMode = mode;
    f.opacity = opacity;
    return f;
}

function fillWhite(doc, layer) {
    doc.activeLayer = layer;
    doc.selection.selectAll();
    doc.selection.fill(colourOf("FFFFFF", "FFFFFF"));
    doc.selection.deselect();
}

function findEdges(doc, layer) {
    doc.activeLayer = layer;
    executeAction(cid("FndE"), undefined, DialogModes.NO);
}

// Keep `colour` (0..1) of the layer's saturation.
function partialDesaturate(doc, layer, colour) {
    if (colour >= 0.99) { return layer; }
    var g = dupAbove(doc, layer, "Desat");
    g.desaturate();
    g.opacity = (1 - colour) * 100;
    return mergeDown(doc, g);
}

// Photoshop's Select Subject (Photoshop 2020 or later).
function selectSubject(doc) {
    try {
        var d = new ActionDescriptor();
        d.putBoolean(sid("sampleAllLayers"), false);
        executeAction(sid("autoCutout"), d, DialogModes.NO);
    } catch (e) {
        note("Select Subject failed: " + e);
        return false;
    }
    try {
        var b = doc.selection.bounds;
        return b !== undefined;
    } catch (e2) {
        return false;
    }
}

// Layer mask on the active layer, revealing the current selection.
function maskFromSelection() {
    var d = new ActionDescriptor();
    d.putClass(cid("Nw  "), cid("Chnl"));
    var r = new ActionReference();
    r.putEnumerated(cid("Chnl"), cid("Chnl"), cid("Msk "));
    d.putReference(cid("At  "), r);
    d.putEnumerated(cid("Usng"), cid("UsrM"), cid("RvlS"));
    executeAction(cid("Mk  "), d, DialogModes.NO);
}

// ------------------------------------------------------------ techniques

// A layer of dark lines on white above `base`, set to Multiply.
function inkLayer(doc, base, p) {
    var ink = dupAbove(doc, base, "Ink");
    var simplify = num(p.simplify, 0, 8, 2);
    if (simplify >= 1) { ink.applyMedianNoise(simplify); }
    ink.desaturate();
    var c = num(p.contrast, 0, 1, 0.5);
    if (p.method === "highpass") {
        ink.applyHighPass(num(p.detail, 1, 10, 3));
        ink.threshold(Math.round(120 + c * 7));
    } else {
        findEdges(doc, ink);
        ink.desaturate();
        ink.adjustLevels(Math.round(40 + 120 * c), Math.round(250 - 30 * c), 1.0, 0, 255);
    }
    var w = num(p.weight, 0, 4, 1);
    if (w >= 0.5) { ink.applyMinimum(w); }
    ink.blendMode = BlendMode.MULTIPLY;
    ink.opacity = num(p.opacity, 0, 100, 100);
    return ink;
}

// Soft, simplified, lightened colour like a wash of paint.
function wash(doc, layer, p) {
    doc.activeLayer = layer;
    layer.applyMedianNoise(num(p.simplify, 1, 12, 5));
    var soft = num(p.softness, 0, 10, 2);
    if (soft > 0) { layer.applyGaussianBlur(soft); }
    var light = num(p.lightness, 0, 1, 0.5);
    layer.adjustLevels(0, 255, 1 + light * 0.6, Math.round(light * 110), 255);
    return partialDesaturate(doc, layer, num(p.colour, 0, 1, 0.6));
}

var OPS = {};

OPS.keep = function (doc, l, p) { return l; };

OPS.ink_lines = function (doc, l, p) {
    var ink = inkLayer(doc, l, p);
    ink.opacity = 100;
    fillWhite(doc, l);
    return mergeDown(doc, ink);
};

OPS.ink_and_wash = function (doc, l, p) {
    var ink = inkLayer(doc, l, {
        method: p.line_method, detail: p.line_detail, weight: p.line_weight,
        contrast: p.line_contrast, simplify: p.line_simplify, opacity: p.line_opacity
    });
    wash(doc, l, {
        colour: p.wash_colour, simplify: p.wash_simplify,
        softness: p.wash_softness, lightness: p.wash_lightness
    });
    return mergeDown(doc, ink);
};

OPS.watercolour = function (doc, l, p) {
    return OPS.ink_and_wash(doc, l, {
        line_method: "edges", line_detail: 3, line_weight: 0, line_contrast: 0.3,
        line_simplify: 3, line_opacity: num(p.edge_opacity, 0, 100, 35),
        wash_colour: num(p.colour, 0, 1, 0.9), wash_simplify: num(p.simplify, 1, 12, 7),
        wash_softness: num(p.softness, 0, 10, 3), wash_lightness: num(p.lightness, 0, 1, 0.4)
    });
};

// Classic pencil sketch: desaturate, inverted copy in Colour Dodge, blur, merge.
OPS.graphite_pencil = function (doc, l, p) {
    doc.activeLayer = l;
    l.desaturate();
    var inv = dupAbove(doc, l, "Dodge");
    inv.invert();
    inv.blendMode = BlendMode.COLORDODGE;
    inv.applyGaussianBlur(num(p.softness, 1, 40, 8));
    l = mergeDown(doc, inv);
    var dark = num(p.darkness, 0, 1, 0.5);
    l.adjustLevels(Math.round(dark * 120), 255, 1 - dark * 0.6, 0, 255);
    var grain = num(p.grain, 0, 20, 4);
    if (grain > 0) { l.applyAddNoise(grain, NoiseDistribution.GAUSSIAN, true); }
    var hatch = num(p.hatching, 0, 12, 0);
    if (hatch > 0) { l.applyMotionBlur(num(p.angle, -90, 90, 45), hatch); }
    return l;
};

OPS.charcoal = function (doc, l, p) {
    l = OPS.graphite_pencil(doc, l, {
        softness: num(p.softness, 1, 40, 20), darkness: num(p.darkness, 0, 1, 0.8),
        grain: num(p.grain, 0, 20, 10), hatching: 0
    });
    doc.activeLayer = l;
    l.applyGaussianBlur(1.2);
    return l;
};

OPS.flat_colour = function (doc, l, p) {
    var o = num(p.outline_opacity, 0, 100, 60);
    var ink = null;
    if (o > 0) {
        ink = inkLayer(doc, l, { method: "edges", contrast: 0.7, simplify: 4, weight: 1, opacity: o });
    }
    doc.activeLayer = l;
    l.applyMedianNoise(num(p.simplify, 1, 12, 6));
    l.posterize(Math.round(num(p.levels, 2, 12, 5)));
    return ink ? mergeDown(doc, ink) : l;
};

OPS.monochrome = function (doc, l, p) {
    doc.activeLayer = l;
    l.desaturate();
    var c = num(p.contrast, 0, 1, 0.4);
    l.adjustLevels(Math.round(c * 40), Math.round(255 - c * 40), 1.0, 0, 255);
    return l;
};

OPS.tint = function (doc, l, p) {
    var f = fillLayerAbove(doc, l, colourOf(p.colour, "704214"), BlendMode.COLORBLEND, num(p.opacity, 0, 100, 60));
    return mergeDown(doc, f);
};

OPS.blur = function (doc, l, p) {
    doc.activeLayer = l;
    var r = num(p.radius, 0, 30, 6);
    if (r > 0) { l.applyGaussianBlur(r); }
    return l;
};

// Whole-image finishing steps, applied after the regions are combined.
var FINISH = {};

FINISH.paper = function (doc, l, p) {
    var f = fillLayerAbove(doc, l, colourOf(p.colour, "F3EAD8"), BlendMode.MULTIPLY, num(p.opacity, 0, 100, 60));
    l = mergeDown(doc, f);
    var g = num(p.grain, 0, 15, 3);
    if (g > 0) { l.applyAddNoise(g, NoiseDistribution.GAUSSIAN, true); }
    return l;
};

FINISH.contrast = function (doc, l, p) {
    var a = num(p.amount, -1, 1, 0.2);
    doc.activeLayer = l;
    if (a >= 0) {
        l.adjustLevels(Math.round(a * 40), Math.round(255 - a * 40), 1.0, 0, 255);
    } else {
        l.adjustLevels(0, 255, 1.0, Math.round(-a * 50), Math.round(255 + a * 30));
    }
    return l;
};

function applyOps(doc, layer, list, table, region) {
    if (!list) { return layer; }
    for (var i = 0; i < list.length; i++) {
        var step = list[i];
        var fn = table[step.op];
        if (!fn) { note(region + ": unknown op " + step.op + " skipped"); continue; }
        try {
            layer = fn(doc, layer, step);
        } catch (e) {
            note(region + ": " + step.op + " failed - " + e + (e.line ? " (line " + e.line + ")" : ""));
        }
    }
    return layer;
}

// ------------------------------------------------------------ one variant

function psagentRun(srcPath, outPath, v, isolate, workSize) {
    PSLOG = [];
    var result = "ERROR: not run";
    var doc = null;
    var oldUnits = app.preferences.rulerUnits;
    app.displayDialogs = DialogModes.NO;
    app.preferences.rulerUnits = Units.PIXELS;
    try {
        doc = app.open(new File(srcPath));
        if (doc.mode !== DocumentMode.RGB) { doc.changeMode(ChangeMode.RGB); }
        if (doc.bitsPerChannel !== BitsPerChannelType.EIGHT) { doc.bitsPerChannel = BitsPerChannelType.EIGHT; }
        doc.flatten();

        var w = doc.width.as("px");
        var h = doc.height.as("px");
        var longest = Math.max(w, h);
        if (workSize > 0 && longest > workSize) {
            var k = workSize / longest;
            doc.resizeImage(UnitValue(Math.round(w * k), "px"), UnitValue(Math.round(h * k), "px"),
                            doc.resolution, ResampleMethod.BICUBIC);
        }

        var src = doc.activeLayer;
        src.isBackgroundLayer = false;
        src.name = "Source";

        var chan = null;
        if (isolate) {
            doc.activeLayer = src;
            if (selectSubject(doc)) {
                var feather = num(v.mask_feather, 0, 20, 2);
                if (feather > 0) { doc.selection.feather(feather); }
                chan = doc.channels.add();
                chan.name = "Subject";
                doc.selection.store(chan, SelectionType.REPLACE);
                doc.selection.deselect();
                doc.activeChannels = doc.componentChannels;
            } else {
                note("Select Subject found nothing: subject steps applied to the whole image");
            }
        }

        if (chan) {
            var bg = dupAbove(doc, src, "Background");
            applyOps(doc, bg, v.background, OPS, "background");
            var sub = src.duplicate(doc.layers[0], ElementPlacement.PLACEBEFORE);
            sub.name = "Subject";
            doc.activeLayer = sub;
            sub = applyOps(doc, sub, v.subject, OPS, "subject");
            doc.activeLayer = sub;
            doc.selection.load(chan, SelectionType.REPLACE, false);
            maskFromSelection();
            doc.selection.deselect();
            chan.remove();
        } else {
            var all = dupAbove(doc, src, "Image");
            applyOps(doc, all, isolate ? v.subject : v.all, OPS, "image");
        }

        src.remove();
        doc.flatten();
        applyOps(doc, doc.activeLayer, v.finish, FINISH, "finish");
        doc.flatten();

        var opts = new JPEGSaveOptions();
        opts.quality = 12;
        opts.embedColorProfile = true;
        opts.formatOptions = FormatOptions.STANDARDBASELINE;
        opts.matte = MatteType.NONE;
        doc.saveAs(new File(outPath), opts, true, Extension.LOWERCASE);
        result = "OK";
    } catch (e) {
        result = "ERROR: " + e + (e.line ? " (line " + e.line + ")" : "");
    } finally {
        if (doc) {
            try { doc.close(SaveOptions.DONOTSAVECHANGES); } catch (e3) { }
        }
        app.preferences.rulerUnits = oldUnits;
    }
    return result + (PSLOG.length ? " | " + PSLOG.join(" ; ") : "");
}
