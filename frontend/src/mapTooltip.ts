import L from "leaflet";
import { previewHeightLimit, previewOffset } from "./mapPreview";

export function bindCampgroundPreview(marker: L.Marker, map: L.Map, html: string, onOpen: () => void, onClose: () => void) {
  let closeTimer: number | undefined;
  const cancelClose = () => window.clearTimeout(closeTimer);
  const closeLater = () => {
    cancelClose();
    closeTimer = window.setTimeout(() => {
      if (!marker.getTooltip()?.getElement()?.contains(document.activeElement)) marker.closeTooltip();
    }, 180);
  };
  const reposition = () => {
    const tooltip = marker.getTooltip(), element = tooltip?.getElement();
    if (!tooltip || !element) return;
    const size = map.getSize();
    const point = map.latLngToContainerPoint(marker.getLatLng());
    element.style.maxWidth = `${Math.max(120, size.x - 24)}px`;
    // Leave both the zoom controls and the source marker accessible.
    element.style.maxHeight = `${Math.min(size.y - 116, previewHeightLimit(point, size))}px`;
    const offset = previewOffset(point, size, element.getBoundingClientRect());
    L.setOptions(tooltip, { offset: L.point(offset.x, offset.y) });
    tooltip.setLatLng(marker.getLatLng());
  };
  const escape = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      if (marker.getTooltip()?.getElement()?.contains(document.activeElement)) marker.getElement()?.focus({ preventScroll: true });
      marker.closeTooltip();
    }
  };
  marker.bindTooltip(html, { className: "campground-preview", direction: "center", interactive: true, opacity: 1 });
  // Keep the card open while moving from its marker onto the card itself.
  marker.off("mouseout", marker.closeTooltip);
  const markerElement = marker.getElement();
  const tabToLinks = (event: KeyboardEvent) => {
    if (event.key !== "Tab" || event.shiftKey || !marker.isTooltipOpen()) return;
    const link = marker.getTooltip()?.getElement()?.querySelector<HTMLAnchorElement>("a[href]");
    if (link) {
      event.preventDefault();
      link.focus({ preventScroll: true });
    }
  };
  if (markerElement) {
    // Leaflet's immediate blur handler would remove the links as focus enters the card.
    L.DomEvent.off(markerElement, "blur", marker.closeTooltip, marker);
    markerElement.addEventListener("blur", closeLater);
    markerElement.addEventListener("keydown", tabToLinks);
  }
  marker.on("mouseover", cancelClose).on("mouseout", closeLater).on("remove", () => {
    cancelClose();
    markerElement?.removeEventListener("blur", closeLater);
    markerElement?.removeEventListener("keydown", tabToLinks);
  });
  marker.on("tooltipopen", () => {
    map.eachLayer(layer => { if (layer instanceof L.Tooltip && layer !== marker.getTooltip()) layer.close(); });
    const element = marker.getTooltip()?.getElement();
    if (element) {
      element.inert = false;
      element.removeAttribute("aria-hidden");
      element.setAttribute("role", "region");
      element.setAttribute("aria-label", "Campground preview");
      element.onmouseenter = cancelClose;
      element.onmouseleave = closeLater;
      element.addEventListener("focusin", cancelClose);
      element.addEventListener("focusout", closeLater);
      element.onkeydown = event => {
        if (event.key === "Tab" && event.shiftKey && document.activeElement === element.querySelector("a[href]")) {
          event.preventDefault();
          markerElement?.focus({ preventScroll: true });
        }
      };
      L.DomEvent.disableClickPropagation(element);
      L.DomEvent.disableScrollPropagation(element);
    }
    reposition();
    map.on("moveend resize", reposition);
    window.addEventListener("keydown", escape);
    onOpen();
  }).on("tooltipclose", () => {
    cancelClose();
    const element = marker.getTooltip()?.getElement();
    if (element) {
      element.inert = true;
      element.setAttribute("aria-hidden", "true");
    }
    map.off("moveend resize", reposition);
    window.removeEventListener("keydown", escape);
    onClose();
  });
  return marker;
}
