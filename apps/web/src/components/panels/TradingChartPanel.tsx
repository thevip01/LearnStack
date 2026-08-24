"use client";

import { TrendingUp } from "lucide-react";
import { NotWired } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { cfgString, cfgStringArray } from "@/lib/utils";

/**
 * A market/candlestick chart. It needs a live price feed that is not part of this
 * phase, so instead of rendering an empty axis it shows an honest "not connected"
 * state describing the chart it will become, with instrument, interval and overlays all
 * read from this panel's own configuration.
 */
export function TradingChartPanel({ panel }: PanelProps) {
  const symbol = cfgString(panel.config, "symbol") ?? cfgString(panel.config, "instrument");
  const interval = cfgString(panel.config, "interval");
  const indicators = cfgStringArray(panel.config, "indicators");

  const shape = [
    symbol ? `Plots OHLC candles for ${symbol}` : "Plots OHLC candles for the instrument",
    interval ? `At a ${interval} interval` : null,
    indicators.length > 0 ? `Overlays ${indicators.join(", ")}` : null,
    "Streams live prices and redraws as each bar closes",
  ].filter((line): line is string => Boolean(line));

  return (
    <NotWired
      title="Market data isn't connected in this build"
      description="A live trading chart needs a market data feed, which lands in a later phase. Its instrument and overlays are already pinned by this panel's configuration."
      shape={shape}
      icon={<TrendingUp className="size-5" aria-hidden />}
    />
  );
}
