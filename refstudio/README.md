# RefStudio

**Make new pictures of a real place or thing, from photos you've taken.**

You give RefStudio a few of your own photos of something, say the Spinnaker Tower, and describe a new picture: a different viewpoint, time of day, weather or style. RefStudio studies your photos and paints the new picture, keeping the subject looking like the real thing.

Everything runs on the Mac Studio. No photos or prompts leave your computer.

| You give it… | …and a description | It makes |
|---|---|---|
| ![Three reference photos of the Spinnaker Tower](images/example-references.jpg) | *"The tower from the reference images, seen from the deck of a sailing yacht in the Solent at golden hour, rigging framing the left edge"* | ![The Spinnaker Tower seen from a yacht at golden hour](images/example-yacht.jpg) |

None of the three photos was taken from a yacht. The view, the light and the rigging are all new, but the tower is recognisably the Spinnaker.

---

## Why you need it

AI image generators learn from millions of pictures, but they don't know every particular building, boat or object. Ask one for "the Spinnaker Tower" and you get a generic TV tower, because that's its best guess at what the name means.

RefStudio fixes that by **showing** the AI what the subject really looks like, instead of telling it a name.

## How it works, in plain terms

1. **You drop in reference photos.** These are your evidence of what the subject looks like.
2. **You write a description** of the picture you want.
3. **RefStudio sends both to ComfyUI**, the image-generating program on the Mac Studio. ComfyUI runs **FLUX.2**, an AI model that can take reference images as well as text.
4. **FLUX.2 paints the picture.** It starts from random noise and refines it over 28 rounds ("steps"), each time checking against your description and your photos.
5. **The result is saved** with your photos and settings, so you can repeat or adjust it later.

You don't need to open ComfyUI yourself. RefStudio starts it if it isn't already running.

---

## Starting and stopping

**From Stream Deck:** press the RefStudio button. Your browser opens the RefStudio page.

**From Terminal:**

```zsh
~/AIStudio/refstudio/start.sh     # start it (or just reopen the page if it's already running)
~/AIStudio/refstudio/stop.sh      # stop it
```

The page lives at **http://127.0.0.1:8765**. Bookmark it if you like. Only this Mac can open it.

Closing the browser tab doesn't stop RefStudio, so you can close it and come back later, even in the middle of a generation.

---

## Making a picture, step by step

### 1. Give it a label

A short name for this picture, e.g. *Spinnaker from a yacht*. It becomes the folder name for the results, so keep it descriptive.

### 2. Add reference photos

Drag photos onto the grid, paste them (⌘V), or click **+** to choose files. Each one shows as a numbered thumbnail; click **×** to remove one. You can add up to 16.

### 3. Describe the picture

Write what you want in the **Prompt** box. See *Writing a good prompt* below; this matters more than anything else.

### 4. Pick a shape

| Shape | Size | Good for |
|---|---|---|
| Landscape | 1536 × 1024 | most scenes |
| Portrait | 1024 × 1536 | tall subjects, posters |
| Square | 1248 × 1248 | social media, icons |
| Wide | 1792 × 1008 | panoramas, 16:9 screens |

### 5. Click Generate

The status panel shows what's happening and how long it's taken, and the bar fills as it works. When it's done, the picture appears in the viewer and in **Recent runs** below.

**Cancel** stops a run part-way through.

### Or queue several jobs in a batch

Click **Add to batch** instead of **Generate** to save the job without running it. It appears in the **Batch** panel under the form. Change the label, prompt, photos or settings and add another. You can queue up to 10 jobs, and each can make up to 4 images from up to 16 reference photos. Click **×** to take a job out.

Click **Start batch** to run them one after another, which is handy overnight. Each job gets its own folder, as if you'd clicked Generate. If one job fails, the batch carries on with the next. **Stop batch** stops the job that's running and leaves it and the rest in the queue for next time. Jobs you add while a batch runs wait for the next **Start batch**.

Queued jobs are kept in `Output/.refstudio-queue/`, so they survive closing RefStudio or restarting the Mac.

---

## How long it takes

| Situation | Time |
|---|---|
| First picture after ComfyUI starts | 10–20 minutes, mostly loading about 60 GB of model into memory |
| Each picture after that | about 4 minutes |

Asking for several images at once (the **Images** setting) makes them one after another, so 4 images take about four times as long.

---

## Writing a good prompt

**Describe the subject, don't name it.** Names pull the AI back towards its own guesses. Refer to it as *"the tower from the reference images"*, or describe it: *"a tall white tower with a curved, open-ribbed frame"*.

**Then describe the new picture:**

- **Viewpoint:** *seen from the deck of a yacht*, *from high above*, *from the beach at low tide*
- **Light and time:** *golden hour*, *blue hour*, *overcast winter morning*, *night with fireworks*
- **Weather:** *in heavy rain*, *in sea mist*, *after snow*
- **Foreground and framing:** *rigging framing the left edge*, *wildflowers in the foreground*
- **Medium:** *photograph*, *watercolour painting*, *1930s railway poster*, *pencil sketch*

| Instead of… | Try… |
|---|---|
| *Spinnaker Tower at night* | *The tower from the reference images at night, floodlit from below, reflections in calm harbour water, long-exposure photograph* |
| *Spinnaker Tower painting* | *Loose watercolour painting of the tower from the reference images rising over a harbour with moored yachts, soft washes, white paper showing through* |

**Words in the picture** (a title or a sign): put the exact words in quotes and say where they go, e.g. *the title "PORTSMOUTH" in bold capitals across the top*. Keep it to a word or two; longer text tends to be misspelled.

---

## Choosing reference photos

- **Three to six photos is the sweet spot.** One photo can work. Many more rarely helps.
- **Show the subject from different sides.** The AI builds its idea of the shape from all of them.
- **Make the subject big and clear.** Close-ups and side-on views beat distant shots where it's tiny.
- **Avoid confusing photos:** heavy crops, strong filters, or other big subjects competing for attention.

**Why not use all 16?** RefStudio has a fixed amount of detail to share between the photos. With 1–4 photos each is used at full detail; with 16, each gets a quarter of that. FLUX.2 is also only documented for up to 10 references. The page warns you above 10.

---

## The settings

| Setting | What it does | Usually |
|---|---|---|
| **Images** | How many pictures to make, each with the next seed | 1 while experimenting |
| **Steps** | How many refining rounds. More is slower; past about 30 it rarely looks better | 28 |
| **Guidance** | How strictly the AI follows your words. Higher sticks closer to the prompt but can look harsh | 4 |
| **Seed** | The starting point for the random noise. Same seed, prompt and photos = the same picture. Leave blank for a new one each time | blank |
| **Free Ollama's memory first** | Unloads the chat AI (Gemma) so FLUX.2 has room to run | on |

**A useful trick:** when you get a picture you nearly like, note its seed (shown under the picture), type it into **Seed**, and change only the prompt. The new picture keeps the same overall composition.

---

## Your results

Every run is saved in its own folder:

```
~/AIStudio/Output/2026/10/2026-10-29 Spinnaker from a yacht/
    Image_01.png          the picture (Image_02.png and so on if you asked for more)
    references/           copies of the photos you used
    Metadata.json         prompt, settings, seed and timings
    Generation.log        a timestamped record of the run
    Workflow.json         the exact job sent to ComfyUI
```

If you reuse a label, the new folder gets *(2)*, *(3)* and so on, so nothing is overwritten.

**Under each picture:**

- **Open full size:** view it at full resolution in a new tab.
- **Use as reference:** add this result to your reference photos, to build on it.
- **Reuse settings:** load this run's label, prompt, settings and photos back into the form.
- **Show folder:** open the run's folder in Finder.

Click any card in **Recent runs** to see an older run again.

A cancelled run that hadn't produced a picture is deleted. A run that failed is kept with *(failed)* on the end of its name, so you can read its `Generation.log`.

---

## When something goes wrong

| What you see | What to do |
|---|---|
| The page won't open | Run `~/AIStudio/refstudio/start.sh` in Terminal. If it says it didn't start, look in `~/AIStudio/refstudio/refstudio.log`. |
| "ComfyUI isn't answering" | ComfyUI failed to start. Check `~/ComfyUI/user/comfyui.log`, or restart the Mac and try again. |
| "ComfyUI stopped during generation" | Usually out of memory. Quit big apps (Photoshop, Lightroom), leave *Free Ollama's memory* ticked, and try again. |
| "Model … not found" | A model file is missing or misnamed in `~/ComfyUI/models/`. The message says which one and where it belongs. |
| The first run seems stuck | It's probably still loading the model. Allow 20 minutes the first time. |
| The subject doesn't look right | Use 3–6 clear photos from different sides, describe the subject instead of naming it, and try a few seeds. |
| Words are misspelled | Shorten them to one or two words, in quotes. |
| A photo won't add | It may be an unusual format. Export it as a JPEG and drop that in instead. |

---

## Words you might meet

| Term | Meaning |
|---|---|
| **ComfyUI** | The program on the Mac Studio that runs AI image models. RefStudio drives it for you. |
| **FLUX.2** | The AI model that makes the pictures. RefStudio uses a compressed version (*Q6_K GGUF*) that suits Apple computers. |
| **Reference image** | A photo you supply to show the AI what something looks like. |
| **Prompt** | Your written description of the picture you want. |
| **Steps** | The number of refining rounds the model takes. |
| **Guidance** | How closely the model follows the prompt. |
| **Seed** | The number that sets the starting noise. It makes results repeatable. |
| **Ollama / Gemma** | The local chat AI used elsewhere in AIStudio. It shares memory with FLUX.2, hence the option to unload it. |

---

*RefStudio is part of AIStudio. The code is `app.py` (the server) and `index.html` (the page) in this folder.*
