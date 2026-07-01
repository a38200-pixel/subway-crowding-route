import { useEffect, useMemo, useRef, useState } from "react";

function formatStation(station) {
  if (!station) return "미선택";
  return `${station.station_name} (${station.line})`;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function useViewportSize(ref) {
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    if (!ref.current) return;

    const resize = () => {
      const rect = ref.current.getBoundingClientRect();
      setSize({ width: rect.width, height: rect.height });
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(ref.current);
    window.addEventListener("resize", resize);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", resize);
    };
  }, [ref]);

  return size;
}

function SubwayMap({
  image,
  hotspots,
  departure,
  arrival,
  onSelectHotspot,
}) {
  const viewportRef = useRef(null);
  const pointerStateRef = useRef(null);
  const size = useViewportSize(viewportRef);

  const minScale = useMemo(() => {
    if (!image || !size.width || !size.height) return 1;
    return Math.min(size.width / image.width, size.height / image.height);
  }, [image, size.width, size.height]);

  const defaultScale = useMemo(() => clamp(minScale * 2.05, minScale, minScale * 6), [minScale]);
  const maxScale = useMemo(() => minScale * 7.5, [minScale]);

  const [transform, setTransform] = useState({ scale: 1, x: 0, y: 0 });

  useEffect(() => {
    if (!image || !size.width || !size.height || !minScale) return;
    const scale = defaultScale;
    const x = (size.width - image.width * scale) / 2;
    const y = (size.height - image.height * scale) / 2;
    setTransform({ scale, x, y });
  }, [defaultScale, image, minScale, size.height, size.width]);

  const normalizeTransform = (next) => {
    if (!image || !size.width || !size.height) return next;

    const scale = clamp(next.scale, minScale, maxScale);
    const scaledWidth = image.width * scale;
    const scaledHeight = image.height * scale;
    const minX = Math.min(0, size.width - scaledWidth);
    const maxX = Math.max(0, size.width - scaledWidth);
    const minY = Math.min(0, size.height - scaledHeight);
    const maxY = Math.max(0, size.height - scaledHeight);

    return {
      scale,
      x: clamp(next.x, minX, maxX),
      y: clamp(next.y, minY, maxY),
    };
  };

  const zoomAroundPoint = (nextScale, originX, originY) => {
    setTransform((current) => {
      const scale = clamp(nextScale, minScale, maxScale);
      const imageX = (originX - current.x) / current.scale;
      const imageY = (originY - current.y) / current.scale;
      const next = {
        scale,
        x: originX - imageX * scale,
        y: originY - imageY * scale,
      };
      return normalizeTransform(next);
    });
  };

  const resetView = () => {
    if (!image || !size.width || !size.height) return;
    const scale = defaultScale;
    setTransform({
      scale,
      x: (size.width - image.width * scale) / 2,
      y: (size.height - image.height * scale) / 2,
    });
  };

  const zoomToOverview = () => {
    if (!image || !size.width || !size.height) return;
    const scale = minScale;
    setTransform({
      scale,
      x: (size.width - image.width * scale) / 2,
      y: (size.height - image.height * scale) / 2,
    });
  };

  const handleWheel = (event) => {
    event.preventDefault();
    if (!viewportRef.current) return;
    const rect = viewportRef.current.getBoundingClientRect();
    const originX = event.clientX - rect.left;
    const originY = event.clientY - rect.top;
    const deltaScale = event.deltaY < 0 ? 1.12 : 0.88;
    zoomAroundPoint(transform.scale * deltaScale, originX, originY);
  };

  const handlePointerDown = (event) => {
    if (event.target.dataset.hotspot === "true") return;
    pointerStateRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      baseX: transform.x,
      baseY: transform.y,
    };
  };

  const handlePointerMove = (event) => {
    if (!pointerStateRef.current) return;
    const deltaX = event.clientX - pointerStateRef.current.startX;
    const deltaY = event.clientY - pointerStateRef.current.startY;
    setTransform((current) =>
      normalizeTransform({
        ...current,
        x: pointerStateRef.current.baseX + deltaX,
        y: pointerStateRef.current.baseY + deltaY,
      })
    );
  };

  const handlePointerUp = () => {
    pointerStateRef.current = null;
  };

  const selectedKeys = new Set(
    [departure?.station_key, arrival?.station_key].filter(Boolean)
  );

  return (
    <section className="map-shell">
      <div className="map-toolbar">
        <button type="button" className="ghost-btn" onClick={zoomToOverview}>
          전체보기
        </button>
        <button type="button" className="ghost-btn" onClick={resetView}>
          기본화면
        </button>
        <button
          type="button"
          className="ghost-btn"
          onClick={() =>
            zoomAroundPoint(
              transform.scale * 1.12,
              size.width / 2,
              size.height / 2
            )
          }
        >
          확대
        </button>
        <button
          type="button"
          className="ghost-btn"
          onClick={() =>
            zoomAroundPoint(
              transform.scale * 0.88,
              size.width / 2,
              size.height / 2
            )
          }
        >
          축소
        </button>
      </div>

      <div
        ref={viewportRef}
        className="map-viewport"
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerLeave={handlePointerUp}
      >
        <div
          className="map-stage"
          style={{
            width: image?.width ?? 0,
            height: image?.height ?? 0,
            transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
          }}
        >
          {image ? (
            <img
              className="map-image"
              src={image.url}
              alt="서울 지하철 노선도"
              draggable="false"
            />
          ) : null}
          {hotspots.map((hotspot) => {
            const isSelected = selectedKeys.has(hotspot.station_key);
            return (
              <button
                key={hotspot.station_key}
                type="button"
                data-hotspot="true"
                className={`hotspot-dot ${isSelected ? "is-selected" : ""}`}
                style={{
                  left: `${hotspot.x}px`,
                  top: `${hotspot.y}px`,
                }}
                onClick={(event) => {
                  event.stopPropagation();
                  onSelectHotspot(hotspot);
                }}
                title={`${hotspot.station_name} (${hotspot.line})`}
              />
            );
          })}
        </div>
      </div>
    </section>
  );
}

function CandidateSheet({ candidates, onPick, onClose }) {
  if (!candidates.length) return null;
  return (
    <div className="candidate-sheet">
      <div className="candidate-sheet__header">
        <div>
          <strong>같은 위치의 역 후보</strong>
          <p>호선을 선택해 역을 확정하세요.</p>
        </div>
        <button type="button" className="icon-btn" onClick={onClose}>
          ×
        </button>
      </div>
      <div className="candidate-list">
        {candidates.map((candidate) => (
          <button
            key={candidate.station_key}
            type="button"
            className="candidate-item"
            onClick={() => onPick(candidate)}
          >
            <span>{candidate.station_name}</span>
            <em>{candidate.line}</em>
          </button>
        ))}
      </div>
    </div>
  );
}

function RouteSection({ payload, loading }) {
  if (loading) {
    return <section className="result-panel">경로를 계산하는 중입니다.</section>;
  }
  if (!payload) return null;

  const routes = payload.routes || [];
  if (!routes.length) {
    return <section className="result-panel">표시할 추천 경로가 없습니다.</section>;
  }

  const route = routes[0];
  const segmentRows = route.segment_rows || [];

  return (
    <section className="result-panel">
      <div className="result-panel__header">
        <div>
          <h3>예상 혼잡도 추천 결과</h3>
          <p>{payload.mode === "sample" ? "샘플 데이터 모드" : "실시간 추천 결과"}</p>
        </div>
        <span className="route-badge">{route.total_travel_minutes}분</span>
      </div>

      <div className="route-summary">
        <article className="route-card">
          <strong>{route.label}</strong>
          <div className="route-metrics">
            <span>예상 혼잡도 {route.weighted_average_congestion}</span>
            <span>공식 평균 기준 {route.weighted_average_congestion_level}</span>
            <span>환승 {route.transfer_count}회</span>
          </div>
        </article>
      </div>

      <div className="segment-chart">
        {segmentRows.map((row) => {
          const congestion = Number(row.congestion || 0);
          return (
            <div key={`${row.segment_index}-${row.to_station}`} className="segment-chart__row">
              <div className="segment-chart__label">
                {row.from_station} → {row.to_station}
              </div>
              <div className="segment-chart__bar-wrap">
                <div
                  className="segment-chart__bar"
                  style={{ width: `${Math.min(congestion, 180) / 1.8}%` }}
                />
              </div>
              <span className="segment-chart__value">{congestion || "-"}</span>
            </div>
          );
        })}
      </div>
    </section>
  );
}

export default function App() {
  const [mapData, setMapData] = useState(null);
  const [loadingMap, setLoadingMap] = useState(true);
  const [mapError, setMapError] = useState("");
  const [departure, setDeparture] = useState(null);
  const [arrival, setArrival] = useState(null);
  const [selectionMode, setSelectionMode] = useState("departure");
  const [autoAssign, setAutoAssign] = useState(true);
  const [pendingCandidates, setPendingCandidates] = useState([]);
  const [routePayload, setRoutePayload] = useState(null);
  const [routeLoading, setRouteLoading] = useState(false);
  const [toast, setToast] = useState("");

  useEffect(() => {
    const load = async () => {
      setLoadingMap(true);
      try {
        const response = await fetch("/api/map-data");
        const payload = await response.json();
        setMapData(payload);
        setMapError("");
      } catch (error) {
        setMapError("지도 데이터를 불러오지 못했습니다.");
      } finally {
        setLoadingMap(false);
      }
    };
    load();
  }, []);

  const applySelection = (station) => {
    if (selectionMode === "departure") {
      setDeparture(station);
      if (autoAssign) setSelectionMode("arrival");
      setToast(`출발역 선택: ${station.station_name} (${station.line})`);
    } else {
      setArrival(station);
      setToast(`도착역 선택: ${station.station_name} (${station.line})`);
    }
    setPendingCandidates([]);
  };

  const handleHotspotSelect = (hotspot) => {
    if (!mapData) return;
    const siblings = mapData.hotspots.filter(
      (candidate) =>
        Math.abs(candidate.x - hotspot.x) <= 1 &&
        Math.abs(candidate.y - hotspot.y) <= 1
    );
    if (siblings.length > 1) {
      setPendingCandidates(siblings);
      return;
    }
    applySelection(hotspot);
  };

  const handleSwap = () => {
    setDeparture(arrival);
    setArrival(departure);
    setToast("출발역과 도착역을 바꿨습니다.");
  };

  const handleReset = () => {
    setDeparture(null);
    setArrival(null);
    setSelectionMode("departure");
    setPendingCandidates([]);
    setRoutePayload(null);
    setToast("선택을 초기화했습니다.");
  };

  const handleRecommend = async () => {
    if (!departure || !arrival) {
      setToast("출발역과 도착역을 모두 선택하세요.");
      return;
    }

    setRouteLoading(true);
    try {
      const response = await fetch("/api/recommendations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          departure_station: departure,
          arrival_station: arrival,
        }),
      });
      const payload = await response.json();
      setRoutePayload(payload);
      setToast(payload.warning || "추천 경로를 불러왔습니다.");
    } catch (error) {
      setToast("추천 결과를 불러오지 못했습니다.");
    } finally {
      setRouteLoading(false);
    }
  };

  return (
    <div className="app-shell">
      <header className="top-nav">
        <div className="top-nav__time">예상 혼잡도</div>
        <div className="top-nav__actions">
          <button type="button" className="nav-icon">검색</button>
          <button type="button" className="nav-icon">최근</button>
          <button type="button" className="nav-icon">빠른선택</button>
          <button type="button" className="nav-icon">설정</button>
        </div>
      </header>

      <div className="service-banner">
        서울 지하철 예상 혼잡도 경로 추천 서비스
      </div>

      <main className="content-shell">
        <section className="status-strip">
          <div className="status-card">
            <span>출발역</span>
            <strong>{formatStation(departure)}</strong>
          </div>
          <div className="status-card">
            <span>도착역</span>
            <strong>{formatStation(arrival)}</strong>
          </div>
        </section>

        <section className="control-strip">
          <button
            type="button"
            className={selectionMode === "departure" ? "pill-btn is-active" : "pill-btn"}
            onClick={() => setSelectionMode("departure")}
          >
            출발역 선택
          </button>
          <button
            type="button"
            className={selectionMode === "arrival" ? "pill-btn is-active" : "pill-btn"}
            onClick={() => setSelectionMode("arrival")}
          >
            도착역 선택
          </button>
          <button type="button" className="pill-btn" onClick={handleSwap}>
            바꾸기
          </button>
          <button type="button" className="pill-btn" onClick={handleReset}>
            초기화
          </button>
          <button type="button" className="primary-btn" onClick={handleRecommend}>
            경로 추천
          </button>
        </section>

        <label className="auto-assign">
          <input
            type="checkbox"
            checked={autoAssign}
            onChange={(event) => setAutoAssign(event.target.checked)}
          />
          첫 선택은 출발역, 다음 선택은 도착역으로 자동 지정
        </label>

        {toast ? <div className="toast-line">{toast}</div> : null}
        {mapData?.warning ? <div className="warning-line">{mapData.warning}</div> : null}
        {mapError ? <div className="warning-line">{mapError}</div> : null}

        <div className="map-region">
          {loadingMap ? (
            <div className="map-loading">노선도 데이터를 불러오는 중입니다.</div>
          ) : mapData ? (
            <SubwayMap
              image={mapData.image}
              hotspots={mapData.hotspots}
              departure={departure}
              arrival={arrival}
              onSelectHotspot={handleHotspotSelect}
            />
          ) : null}
          <CandidateSheet
            candidates={pendingCandidates}
            onPick={applySelection}
            onClose={() => setPendingCandidates([])}
          />
        </div>

        <RouteSection payload={routePayload} loading={routeLoading} />
      </main>
    </div>
  );
}
