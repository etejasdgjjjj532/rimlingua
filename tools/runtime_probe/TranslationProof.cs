// Diagnostic MOD used only inside a disposable RimWorld runtime.
using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Xml;
using RimWorld;
using UnityEngine;
using Verse;

namespace RimWorldTranslatorProof
{
    [StaticConstructorOnStartup]
    public static class TranslationProof
    {
        static TranslationProof()
        {
            string fixture = null;
            foreach (string argument in Environment.GetCommandLineArgs())
                if (argument.StartsWith("-rwt-proof-fixture=", StringComparison.Ordinal))
                    fixture = argument.Substring("-rwt-proof-fixture=".Length);
            if (fixture == null) return;
            LongEventHandler.ExecuteWhenFinished(delegate
            {
                try
                {
                    var driver = new GameObject("RimWorld Translation Proof Driver");
                    UnityEngine.Object.DontDestroyOnLoad(driver);
                    driver.AddComponent<ProofDriver>().fixture = fixture;
                }
                catch (Exception exception) { Log.Error("[RWT-PROOF] " + exception); }
            });
        }
    }

    public sealed class ProofDriver : MonoBehaviour
    {
        public string fixture;
        private bool opened;

        public void Update()
        {
            // Static constructors finish before PlayDataLoader and UIRoot_Entry.
            // Wait for both real language injection and real UI initialization.
            if (opened || fixture == null || !PlayDataLoader.Loaded || LongEventHandler.ShouldWaitForEvent)
                return;
            if (Find.WindowStack == null || LanguageDatabase.activeLanguage == null) return;
            try
            {
                opened = true;
                Find.WindowStack.Add(new ProofWindow(fixture));
                UnityEngine.Object.Destroy(gameObject);
            }
            catch (Exception exception) { Log.Error("[RWT-PROOF] " + exception); }
        }
    }

    public sealed class Observation
    {
        public string sourceId, modName, defName, expected, actual;
        public bool found;
        public bool Matches { get { return found && actual == expected; } }
    }

    public sealed class ProofWindow : Window
    {
        private readonly List<Observation> observations = new List<Observation>();
        private readonly string reportPath;
        private readonly string screenshotPath;
        private readonly float openedAt;
        private int renderedFrames;
        private bool screenshotRequested;

        public override Vector2 InitialSize { get { return new Vector2(970f, 660f); } }

        public ProofWindow(string fixture)
        {
            var xml = new XmlDocument();
            xml.Load(fixture);
            reportPath = xml.DocumentElement.GetAttribute("report");
            screenshotPath = xml.DocumentElement.GetAttribute("screenshot");
            foreach (XmlElement item in xml.SelectNodes("/TranslationProof/Item"))
            {
                var value = new Observation();
                value.sourceId = item.GetAttribute("sourceId");
                value.modName = item.GetAttribute("modName");
                value.defName = item.GetAttribute("defName");
                value.expected = item.InnerText;
                // Optional defType + stage: a list item's label (HediffDef / ThoughtDef stages) instead of a ThingDef label.
                string defType = item.GetAttribute("defType");
                int stage = item.HasAttribute("stage") ? int.Parse(item.GetAttribute("stage")) : -1;
                if (stage >= 0 && defType == "HediffDef")
                {
                    HediffDef hediff = DefDatabase<HediffDef>.GetNamedSilentFail(value.defName);
                    value.found = hediff != null && hediff.stages != null && stage < hediff.stages.Count;
                    value.actual = value.found ? (hediff.stages[stage].label ?? "<null>") : "<missing HediffDef stage>";
                }
                else if (stage >= 0 && defType == "ThoughtDef")
                {
                    ThoughtDef thought = DefDatabase<ThoughtDef>.GetNamedSilentFail(value.defName);
                    value.found = thought != null && thought.stages != null && stage < thought.stages.Count;
                    value.actual = value.found ? (thought.stages[stage].label ?? "<null>") : "<missing ThoughtDef stage>";
                }
                else
                {
                    ThingDef definition = DefDatabase<ThingDef>.GetNamedSilentFail(value.defName);
                    value.found = definition != null;
                    value.actual = definition == null ? "<missing ThingDef>" : definition.label;
                }
                observations.Add(value);
            }
            doCloseX = false;
            doCloseButton = false;
            closeOnAccept = false;
            closeOnCancel = false;
            absorbInputAroundWindow = true;
            forcePause = true;
            openedAt = Time.realtimeSinceStartup;
            WriteReport();
            Log.Message("[RWT-PROOF] Read " + observations.Count + " actual ThingDef labels.");
        }

        public override void DoWindowContents(Rect inRect)
        {
            Text.Font = GameFont.Medium;
            Widgets.Label(new Rect(0, 0, inRect.width, 36), "SOL RIMWORLD TRANSLATION PROOF");
            Text.Font = GameFont.Small;
            Widgets.Label(new Rect(0, 42, inRect.width, 28),
                "Actual DefDatabase<ThingDef>.label values rendered in a diagnostic Verse.Window");
            Widgets.Label(new Rect(0, 72, inRect.width, 24),
                "This is a runtime diagnostic window; it is not a normal gameplay screen.");
            float y = 110;
            foreach (Observation value in observations)
            {
                GUI.color = new Color(0.78f, 0.82f, 0.88f);
                Widgets.Label(new Rect(0, y, inRect.width, 24), value.sourceId + "  " + value.modName);
                GUI.color = Color.white;
                Text.Font = GameFont.Medium;
                // Only the actual loaded value is rendered. Expected values never appear here.
                Widgets.Label(new Rect(12, y + 27, inRect.width - 24, 36), value.actual);
                Text.Font = GameFont.Small;
                y += 78;
            }
            GUI.color = Color.white;
            if (Event.current.type == EventType.Repaint) renderedFrames++;
        }

        public override void WindowUpdate()
        {
            base.WindowUpdate();
            if (!screenshotRequested && renderedFrames >= 20 && Time.realtimeSinceStartup - openedAt >= 6f)
            {
                screenshotRequested = true;
                ScreenCapture.CaptureScreenshot(screenshotPath);
                WriteReport();
                Log.Message("[RWT-PROOF] Requested in-game framebuffer screenshot: " + screenshotPath);
            }
        }

        private static string Json(string value)
        {
            if (value == null) return "null";
            var result = new StringBuilder("\"");
            foreach (char character in value)
            {
                switch (character)
                {
                    case '\\': result.Append("\\\\"); break;
                    case '"': result.Append("\\\""); break;
                    case '\n': result.Append("\\n"); break;
                    case '\r': result.Append("\\r"); break;
                    case '\t': result.Append("\\t"); break;
                    default:
                        if (character < 32) result.Append("\\u" + ((int)character).ToString("x4"));
                        else result.Append(character);
                        break;
                }
            }
            return result.Append('"').ToString();
        }

        private void WriteReport()
        {
            var json = new StringBuilder();
            json.Append("{\"schema\":1,\"evidence_kind\":\"diagnostic_actual_game_window\",");
            json.Append("\"active_language\":" + Json(LanguageDatabase.activeLanguage.folderName) + ",");
            json.Append("\"rendered_frames\":" + renderedFrames + ",");
            json.Append("\"screenshot_requested\":" + (screenshotRequested ? "true" : "false") + ",");
            json.Append("\"screenshot\":" + Json(screenshotPath) + ",\"observations\":[");
            for (int index = 0; index < observations.Count; index++)
            {
                if (index != 0) json.Append(',');
                Observation value = observations[index];
                json.Append("{\"source_id\":" + Json(value.sourceId));
                json.Append(",\"mod_name\":" + Json(value.modName));
                json.Append(",\"def_name\":" + Json(value.defName));
                json.Append(",\"expected\":" + Json(value.expected));
                json.Append(",\"actual\":" + Json(value.actual));
                json.Append(",\"found\":" + (value.found ? "true" : "false"));
                json.Append(",\"injection_match\":" + (value.Matches ? "true" : "false") + "}");
            }
            json.Append("]}\n");
            File.WriteAllText(reportPath, json.ToString(), new UTF8Encoding(false));
        }
    }
}
