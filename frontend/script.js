import { foulWords } from './foul.js';

document.addEventListener("DOMContentLoaded", () => {
  const menuItems = document.querySelectorAll(".menu-item");
  const editable = document.querySelector(".editable");
  const fileUpload = document.getElementById("fileUpload");
  const checkBtn = document.getElementById("checkBtn");
  const refineBtn = document.getElementById("refineBtn");
  const output = document.getElementById("output");
  const loader = document.querySelector(".loader");
  const uploadIcon = document.querySelector(".upload-icon");

  let currentMode = "score";
  let selectedFile = null;

  
  // INPUT BLOCKING LOGIC 

  function placeCaretAtOffset(node, offset) {
    const range = document.createRange();
    const sel = window.getSelection();
    range.setStart(node, offset);
    range.collapse(true);
    sel.removeAllRanges();
    sel.addRange(range);
  }

  function checkCivilityInline() {
    const sel = window.getSelection();
    const caretNode = sel.focusNode;
    const caretOffset = sel.focusOffset;

    const walker = document.createTreeWalker(userInput, NodeFilter.SHOW_TEXT, null, false);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);

    let hasFoul = false;

    nodes.forEach(textNode => {
      const text = textNode.nodeValue;
      if (!text.trim()) return;

      // Skip already wrapped words
      if (textNode.parentNode.classList && textNode.parentNode.classList.contains("bad-word")) return;

      let lastIndex = 0;
      const frag = document.createDocumentFragment();
      let foundFoul = false;

      foulWords.forEach(word => {
        const regex = new RegExp(`\\b(${word})\\b`, "gi");
        text.replace(regex, (match, p1, offset) => {
          if (offset > lastIndex) frag.appendChild(document.createTextNode(text.slice(lastIndex, offset)));

          const span = document.createElement("span");
          span.className = "bad-word";
          span.textContent = match;
          frag.appendChild(span);

          lastIndex = offset + match.length;
          foundFoul = true;
          hasFoul = true;
        });
      });

      if (foundFoul) {
        if (lastIndex < text.length) frag.appendChild(document.createTextNode(text.slice(lastIndex)));
        textNode.parentNode.replaceChild(frag, textNode);
      }
    });

    // Restore caret position
    if (caretNode) {
      // Try to find the closest text node for the caret
      let newNode = caretNode;
      let offset = caretOffset;

      if (caretNode.nodeType === 1 && caretNode.childNodes.length) {
        // if caretNode is element, move to its first text node
        newNode = caretNode.childNodes[Math.min(offset, caretNode.childNodes.length - 1)];
        offset = 0;
      }

      placeCaretAtOffset(newNode, offset);
    }

    // Update output
    if (hasFoul) {
      output.innerHTML = "⚠️ Foul language detected! Please erase the highlighted word to continue typing.";
    } else if (output.innerHTML.includes("⚠️")) {
      output.innerHTML = "";
    }
  }

  // Hook into input
  userInput.addEventListener("input", () => {
    checkCivilityInline();
  });


  //  SIDEBAR SWITCHING
  
  menuItems.forEach(item => {
    item.addEventListener("click", () => {
      menuItems.forEach(i => i.classList.remove("active"));
      item.classList.add("active");
      currentMode = item.dataset.option;
      resetState();
      updateUI();
    });
  });

  function resetState() {
    selectedFile = null;
    fileUpload.value = "";
    output.innerHTML = "";
    editable.innerHTML = "";
    editable.dataset.locked = "false";
  }


  // UI CONTROL

  function updateUI() {
    editable.contentEditable = true;
    checkBtn.style.display = "none";
    refineBtn.style.display = "none";

    uploadIcon.style.display = "flex";

    if (currentMode === "score") {
      editable.dataset.placeholder = "Enter text";
      checkBtn.style.display = "inline-block";
      uploadIcon.style.display = "none";
    }
    else if (currentMode === "text") {
      editable.dataset.placeholder = "Upload your text file";
      refineBtn.style.display = "inline-block";
      fileUpload.accept = ".txt,text/plain";
    }
    else if (currentMode === "image") {
      editable.dataset.placeholder = "Upload your Image";
      editable.contentEditable = false;
      refineBtn.style.display = "inline-block";
      fileUpload.accept = "image/*";
    }
    else if (currentMode === "video") {
      editable.dataset.placeholder = "Upload your Video";
      editable.contentEditable = false;
      refineBtn.style.display = "inline-block";
      fileUpload.accept = "video/*";
    }
  }


  // UPLOADING 

  uploadIcon.addEventListener("click", () => {
    fileUpload.click();
  });

  fileUpload.addEventListener("change", () => {
    selectedFile = fileUpload.files[0];
    if (selectedFile) {
      output.innerHTML = `✅ File selected: <b>${selectedFile.name}</b>`;
    }
  });


  // CHECK CIVILITY SCORE 

  checkBtn.addEventListener("click", async (e) => {

    e.preventDefault();
    const textToCheck = editable.innerText.trim();

    if (!textToCheck) {
      output.innerHTML = "⚠️ Please enter some text to check.";
      return;
    }

    showLoader();

    try {
      const res = await fetch("http://127.0.0.1:5000/check", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: textToCheck })
      });

      const data = await res.json();
      output.innerHTML = `Civility Score: <b>${data.score}/100</b>`;
    } catch {
      output.innerHTML = "❌ Error connecting to server.";
    } finally {
      hideLoader();
    }
  });

  
  // REFINE AND DOWNLOAD 

  refineBtn.addEventListener("click", async (e) => {

    e.preventDefault();
    let fileToUpload = selectedFile;
    const typedText = editable.innerText.trim();

    if (currentMode === "text" && !fileToUpload && typedText) {
      fileToUpload = new File([typedText], "input.txt", { type: "text/plain" });
    }

    if (!fileToUpload) {
      output.innerHTML = "⚠️ Please upload a file or enter text first.";
      return;
    }

    const formData = new FormData();
    formData.append("file", fileToUpload);

    showLoader();

    try {
      const res = await fetch("http://127.0.0.1:5000/refine", {
        method: "POST",
        body: formData
      });

      if (!res.ok) throw new Error();

      const blob = await res.blob();

      // Ensure correct MIME type
      const finalBlob = new Blob([blob], {
        type: res.headers.get("Content-Type") || fileToUpload.type
      });

      const url = window.URL.createObjectURL(finalBlob);

      const link = document.createElement("a");
      link.href = url;
      link.download = `refined_${fileToUpload.name}`;

      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);

      window.URL.revokeObjectURL(url);

      output.innerHTML = "✅ Downloaded refined version successfully.";
    } catch {
      output.innerHTML = "❌ Refinement failed.";
    } finally {
      hideLoader();
      selectedFile = null;
      fileUpload.value = "";
    }
  });

  function showLoader() { loader.style.display = "flex"; }
  function hideLoader() { loader.style.display = "none"; }

  updateUI();
});