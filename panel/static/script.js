// Inicjalizacja zmiennych globalnych
let ctx;
let isDrawing = false;
let currentColor = '#000000';
let currentThickness = 2;
let isErasing = false;

// Po załadowaniu strony
document.addEventListener("DOMContentLoaded", function() {
const canvas = document.getElementById('notebookCanvas');
ctx = canvas.getContext('2d');

canvas.addEventListener('mousedown', startDrawing);
canvas.addEventListener('mouseup', stopDrawing);
canvas.addEventListener('mousemove', draw);

});

// Funkcje rysowania
function startDrawing() {
    isDrawing = true;
}

function stopDrawing() {
    isDrawing = false;
    ctx.beginPath();
}

function draw(event) {
    if (!isDrawing) return;
    ctx.lineWidth = currentThickness;
    ctx.strokeStyle = currentColor;
    ctx.lineCap = 'round';
    ctx.lineTo(event.offsetX, event.offsetY);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(event.offsetX, event.offsetY);
}

// Funkcje panelu kolorów i grubości
function toggleColorPicker() {
    document.getElementById('colorMenu').classList.toggle('active');
}

function setColor(color) {
    currentColor = color;
    document.getElementById('colorMenu').classList.remove('active');
}

function toggleThicknessPicker() {
    document.getElementById('sizeMenu').classList.toggle('active');
}

function setThickness(size) {
    currentThickness = size;
    document.getElementById('sizeMenu').classList.remove('active');
}

// Funkcja gumki
function activateEraser() {
    ctx.globalCompositeOperation = 'destination-out';
    ctx.lineWidth = currentThickness;
}

// Funkcja rysowania (normalne)
function activateDraw() {
    ctx.globalCompositeOperation = 'source-over';
}

// Funkcja otwierająca okno wyboru pliku
function openFilePicker() {
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.jpeg, .jpg, .png, .pdf, .doc, .docx';
    fileInput.onchange = function(event) {
        const file = event.target.files[0];
        if (file) {
            displayFile(file);
        }
    };
    fileInput.click();
}

function displayFile(file) {
    const reader = new FileReader();
    reader.onload = function(e) {
        const fileURL = e.target.result;
        const fileType = file.type;
        let element;

        if (fileType.startsWith('image/')) {
            element = document.createElement('img');
            element.src = fileURL;
        } else if (fileType === 'application/pdf') {
            element = document.createElement('iframe');
            element.src = fileURL;
        } else if (
            file.name.endsWith('.doc') || file.name.endsWith('.docx') ||
            fileType === 'application/msword' ||
            fileType.includes('officedocument')
        ) {
            element = document.createElement('iframe');
            element.src = `https://docs.google.com/gview?url=${encodeURIComponent(fileURL)}&embedded=true`;
        } else {
            alert("Obsługiwane są tylko pliki obrazów, PDF i Word.");
            return;
        }

        // Opakowanie w skalowalny kontener
        const wrapper = document.createElement('div');
        wrapper.classList.add('draggable', 'resizable');
        wrapper.style.position = 'absolute';
        wrapper.style.top = '50px';
        wrapper.style.left = '50px';
        wrapper.style.width = '300px';
        wrapper.style.height = '300px';
        wrapper.style.resize = 'both';
        wrapper.style.overflow = 'hidden';
        wrapper.style.border = '1px solid #ddd';
        wrapper.style.minWidth = '100px';
        wrapper.style.minHeight = '100px';

        element.style.width = '100%';
        element.style.height = '100%';
        element.style.pointerEvents = 'none'; // umożliwia rysowanie na wierzchu

        wrapper.appendChild(element);
        document.querySelector('.virtual-room').appendChild(wrapper);
        makeDraggable(wrapper);
        makeRotatable(wrapper);
        makeResizable(wrapper);
    };

    reader.readAsDataURL(file);
}


// Funkcja umożliwiająca przenoszenie obrazu
function makeDraggable(element) {
    element.addEventListener('mousedown', function(e) {
        let shiftX = e.clientX - element.getBoundingClientRect().left;
        let shiftY = e.clientY - element.getBoundingClientRect().top;

        function moveAt(clientX, clientY) {
            const parent = document.querySelector('.virtual-room');
            const parentRect = parent.getBoundingClientRect();

            let newLeft = clientX - parentRect.left - shiftX;
            let newTop = clientY - parentRect.top - shiftY;

            // Ograniczenia przesuwania
            if (newLeft < 0) newLeft = 0;
            if (newTop < 0) newTop = 0;
            if (newLeft + element.offsetWidth > parent.clientWidth) {
                newLeft = parent.clientWidth - element.offsetWidth;
            }
            if (newTop + element.offsetHeight > parent.clientHeight) {
                newTop = parent.clientHeight - element.offsetHeight;
            }

            element.style.left = newLeft + 'px';
            element.style.top = newTop + 'px';
        }


        function onMouseMove(event) {
            moveAt(event.clientX, event.clientY);
        }

        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', function() {
            document.removeEventListener('mousemove', onMouseMove);
        }, { once: true });
    });

    element.ondragstart = function() {
        return false;
    };
}

function makeRotatable(container) {
    const handle = document.createElement('div');
    handle.classList.add('rotate-handle');
    handle.title = "Obracanie"; // pokaże się dymek po najechaniu
    handle.className = 'rotate-handle';
    container.appendChild(handle);

    let isRotating = false;
    let startAngle = 0;
    let initialAngle = 0;

    handle.addEventListener('mousedown', function (e) {
        e.preventDefault();
        e.stopPropagation();

        const rect = container.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;

        const dx = e.clientX - centerX;
        const dy = e.clientY - centerY;
        startAngle = Math.atan2(dy, dx);
        const currentTransform = container.style.transform;
        const match = currentTransform.match(/rotate\(([-\d.]+)deg\)/);
        initialAngle = match ? parseFloat(match[1]) : 0;

        isRotating = true;

        function onMouseMove(eMove) {
            if (!isRotating) return;

            const dx = eMove.clientX - centerX;
            const dy = eMove.clientY - centerY;
            const currentAngle = Math.atan2(dy, dx);
            const angleDeg = initialAngle + ((currentAngle - startAngle) * (180 / Math.PI));

            container.style.transform = `rotate(${angleDeg}deg)`;
            container.style.transformOrigin = 'center center';
        }

        function onMouseUp() {
            isRotating = false;
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
        }

        document.addEventListener('mousemove', onMouseMove);
        document.addEventListener('mouseup', onMouseUp);
    });
}

function makeResizable(container) {
    const resizer = document.createElement('div');
    resizer.className = 'resize-handle';

    container.appendChild(resizer);

    resizer.addEventListener('mousedown', function (e) {
        e.preventDefault();
        e.stopPropagation();

        const startX = e.clientX;
        const startY = e.clientY;
        const startWidth = parseFloat(getComputedStyle(container, null).width.replace("px", ""));
        const startHeight = parseFloat(getComputedStyle(container, null).height.replace("px", ""));

        function doDrag(e) {
            container.style.width = (startWidth + e.clientX - startX) + 'px';
            container.style.height = (startHeight + e.clientY - startY) + 'px';
        }

        function stopDrag() {
            document.removeEventListener('mousemove', doDrag);
            document.removeEventListener('mouseup', stopDrag);
        }

        document.addEventListener('mousemove', doDrag);
        document.addEventListener('mouseup', stopDrag);
    });
}

function toggleGridMenu() {
    document.getElementById('gridMenu').classList.toggle('active');
}

function addGrid(size) {
    const oldGrid = document.getElementById('gridOverlay');
    if (oldGrid) oldGrid.remove();

    const canvas = document.getElementById('notebookCanvas');
    const overlay = document.createElement('canvas');
    overlay.width = canvas.width;
    overlay.height = canvas.height;
    overlay.id = 'gridOverlay';
    overlay.className = 'canvas-grid';

    const ctx = overlay.getContext('2d');
    ctx.strokeStyle = '#cccccc';
    ctx.lineWidth = 1;

    let step;
    switch (size) {
        case 'small': step = 20; break;
        case 'medium': step = 40; break;
        case 'large': step = 60; break;
        default: step = 40;
    }

    for (let x = step; x < overlay.width; x += step) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, overlay.height);
        ctx.stroke();
    }

    for (let y = step; y < overlay.height; y += step) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(overlay.width, y);
        ctx.stroke();
    }

    // 🔴 KLUCZOWE: kratka pod canvasem
    canvas.parentElement.insertBefore(overlay, canvas);
    document.getElementById('gridMenu').classList.remove('active');
}

let isTextMode = false;
let currentTextInput = null;

// Włączenie trybu tekstowego
function activateTextMode() {
    isTextMode = true;
    const canvas = document.getElementById('notebookCanvas');
    canvas.style.cursor = 'text';
    alert("Kliknij na tablicę, aby dodać pole tekstowe.");
}

// Kliknięcie na tablicę – dodaje textarea
document.getElementById("notebookCanvas").addEventListener("mousedown", function (e) {
    if (!isTextMode) return;

    const x = e.offsetX;
    const y = e.offsetY;

    const input = document.createElement("textarea");
    input.className = "text-input";
    input.style.left = x + "px";
    input.style.top = y + "px";
    input.style.color = currentColor;

    document.querySelector(".virtual-room").appendChild(input);
    input.focus();
    currentTextInput = input;

    isTextMode = false; // wyłączenie trybu po dodaniu

    // Klik poza polem wyłącza edycję
    input.addEventListener("blur", function () {
        input.readOnly = true;
        input.style.border = "none";
        input.style.background = "transparent";
        input.style.resize = "none";
    });

    // ESC zamyka edycję
    document.addEventListener("keydown", function escHandler(ev) {
        if (ev.key === "Escape") {
            input.blur();
            document.removeEventListener("keydown", escHandler);
        }
    });
});

let zajecia = [];

function toggleMojeZajecia() {
    const panel = document.getElementById("mojeZajeciaPanel");
    panel.style.display = panel.style.display === "none" ? "block" : "none";
    wyswietlZajecia();
}

function wyswietlZajecia() {
    const lista = document.getElementById("listaZajec");
    const template = document.getElementById("zajecie-template");
    lista.innerHTML = "";

    zajecia.forEach(z => {
        const li = template.content.cloneNode(true);
        li.querySelector(".tytul").textContent = z.tytul;
        li.querySelector(".data").textContent = z.data;
        li.querySelector(".opis").textContent = z.opis;
        lista.appendChild(li);
    });
}

function filtrujZajecia() {
    const temat = document.getElementById("filtrTemat").value.toLowerCase();
    const data = document.getElementById("filtrData").value;
    const lista = document.getElementById("listaZajec").children;

    [...lista].forEach(li => {
        const tytul = li.querySelector(".tytul").textContent.toLowerCase();
        const dataZajec = li.querySelector(".data").textContent;

        const matchTemat = !temat || tytul.includes(temat);
        const matchData = !data || dataZajec === data;

        li.style.display = matchTemat && matchData ? "" : "none";
    });
}

function edytujZajecie(btn) {
    const li = btn.closest("li");
    const nowyTytul = prompt("Nowy tytuł:", li.querySelector(".tytul").textContent);
    const nowyOpis = prompt("Nowy opis:", li.querySelector(".opis").textContent);

    if (nowyTytul) li.querySelector(".tytul").textContent = nowyTytul;
    if (nowyOpis) li.querySelector(".opis").textContent = nowyOpis;
}

function usunZajecie(btn) {
    if (confirm("Czy na pewno chcesz usunąć to zajęcie?")) {
        const li = btn.closest("li");
        li.remove();
    }
}
