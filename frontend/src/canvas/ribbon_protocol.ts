// Message protocol shared between the main thread (RibbonRenderer) and the
// ribbon render worker. The connection layer (block ribbons at low zoom, SCM
// lines at high zoom) is the densest canvas; rendering it off the main thread
// keeps pan/zoom input responsive.
//
// Heavy data (the per-pair blocks/scms arrays) is sent only when it changes;
// the per-frame viewport state is small. The worker caches the last data and
// the last view, and re-renders whenever either arrives — so a data update
// repaints with the latest viewport and vice-versa.

import type { Viewport } from './coords'
import type { AdjacentPair } from './draw_ribbons'
import type { AdjacentPairScms } from './draw_scms'

/** Render inputs that change only when synteny data is (re)fetched. */
export type RibbonData = {
  pairs: AdjacentPair[]
  pairsScms: AdjacentPairScms[]
  /** referenceColorMap serialized as entries (Maps clone, but entries are explicit). */
  colorMap: [string, string][]
}

/** Render inputs that change every frame (pan/zoom/resize/fade/LOD). */
export type RibbonView = {
  viewports: Record<string, Viewport>
  canvasWidth: number
  canvasHeight: number
  dpr: number
  fade: number
  lodMode: 'block' | 'scm'
}

export type InitMessage = { type: 'init'; canvas: OffscreenCanvas }
export type DataMessage = { type: 'data'; data: RibbonData }
export type RenderMessage = { type: 'render'; view: RibbonView }
export type RibbonWorkerMessage = InitMessage | DataMessage | RenderMessage
