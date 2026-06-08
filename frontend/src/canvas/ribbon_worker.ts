/// <reference lib="webworker" />
// Ribbon render worker: owns the connection-layer OffscreenCanvas and draws
// block ribbons / SCM lines off the main thread. See ribbon_protocol.ts.

import { DEFAULT_VIEWPORT, type Viewport } from './coords'
import { drawRibbons } from './draw_ribbons'
import { drawScmLines } from './draw_scms'
import type { RibbonData, RibbonView, RibbonWorkerMessage } from './ribbon_protocol'

let canvas: OffscreenCanvas | null = null
let ctx: OffscreenCanvasRenderingContext2D | null = null
let data: RibbonData | null = null
let view: RibbonView | null = null

self.onmessage = (e: MessageEvent<RibbonWorkerMessage>) => {
  const msg = e.data
  switch (msg.type) {
    case 'init':
      canvas = msg.canvas
      ctx = canvas.getContext('2d')
      break
    case 'data':
      data = msg.data
      render()
      break
    case 'render':
      view = msg.view
      render()
      break
  }
}

function viewportFn(viewports: Record<string, Viewport>): (id: string) => Viewport {
  return (id) => viewports[id] ?? DEFAULT_VIEWPORT
}

function render(): void {
  if (!canvas || !ctx || !data || !view) return
  // Setting width/height resets the canvas (and its transform), so size first
  // then re-apply the DPR transform before drawing.
  const wi = Math.max(1, Math.floor(view.canvasWidth * view.dpr))
  const hi = Math.max(1, Math.floor(view.canvasHeight * view.dpr))
  if (canvas.width !== wi) canvas.width = wi
  if (canvas.height !== hi) canvas.height = hi
  ctx.setTransform(view.dpr, 0, 0, view.dpr, 0, 0)

  const colorMap = new Map(data.colorMap)
  const fn = viewportFn(view.viewports)
  if (view.lodMode === 'scm') {
    drawScmLines(ctx, data.pairsScms, fn, view.canvasWidth, view.canvasHeight, colorMap, view.fade)
  } else {
    drawRibbons(ctx, data.pairs, fn, view.canvasWidth, view.canvasHeight, colorMap, view.fade)
  }
}
