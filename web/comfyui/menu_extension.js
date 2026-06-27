import { app } from "../../scripts/app.js";

// Adds an action-bar button (modern ComfyUI) and a top-menu fallback that
// open the Output Gallery in a new browser tab.

const BUTTON_TOOLTIP = "Output Gallery";

function openGallery() {
    window.open("/gallery", "_blank");
}

function supportsActionBarButtons() {
    const raw = window["__COMFYUI_FRONTEND_VERSION__"];
    if (Array.isArray(raw) && raw.length >= 3) {
        // action_bar_buttons support landed in 1.33.9
        return raw[0] > 1 || (raw[0] === 1 && raw[1] > 33) ||
            (raw[0] === 1 && raw[1] === 33 && raw[2] >= 9);
    }
    return true; // assume modern; DOM fallback covers old versions.
}

const extension = {
    name: "OutputGallery.Menu",
    async setup() {
        if (supportsActionBarButtons()) return; // use actionBarButtons below
        await attachLegacyMenuButton();
    },
};

if (supportsActionBarButtons()) {
    extension.actionBarButtons = [
        {
            icon: "icon-[mdi--image-multiple] size-4",
            tooltip: BUTTON_TOOLTIP,
            onClick: openGallery,
        },
    ];
}

async function attachLegacyMenuButton() {
    try {
        const { ComfyButton } = await import("../../scripts/ui/components/button.js");
        const { ComfyButtonGroup } = await import("../../scripts/ui/components/buttonGroup.js");
        const check = () => {
            const settingsGroup = app.menu?.settingsGroup;
            if (!settingsGroup) {
                return false;
            }
            const button = new ComfyButton({
                icon: "image-multiple",
                tooltip: BUTTON_TOOLTIP,
                action: openGallery,
            });
            const group = new ComfyButtonGroup(button);
            settingsGroup.element.before(group.element);
            return true;
        };
        if (!check()) {
            // Menu may not be ready yet; retry once on next tick.
            setTimeout(check, 1000);
        }
    } catch (err) {
        console.warn("[OutputGallery] could not attach menu button:", err);
    }
}

app.registerExtension(extension);
