# Fuel Route Optimization API: Deep Dive Architecture

This document provides a comprehensive technical breakdown of the system's architecture, request lifecycle, and performance optimizations.

---

## 1. High-Level Request Lifecycle
When a client sends a request to `/api/route-with-fuel/`, the execution flows through five distinct architectural layers.

### **Phase 1: API Entry & Validation**
**File:** `api/views.py` -> `api/serializers.py`
*   **Role:** Handles HTTP concerns.
*   **Logic:** 
    1.  Receives JSON payload (Start, End, Strategy).
    2.  `RouteRequestSerializer` validates coordinates or city strings.
    3.  Calls the **Orchestrator** service.
    4.  Wraps results in a standard response envelope.

### **Phase 2: Orchestration**
**File:** `api/services.py`
*   **Role:** The "Conductor." It manages the sequence of operations.
*   **Key Function:** `plan_route_with_fuel(data)`
*   **Code Flow:**
    ```python
    # 1. Resolve text to coordinates using RoutingService
    # 2. Fetch road geometry (cached or OSRM)
    # 3. Discover fuel stations along that geometry
    # 4. Invoke the Fuel Planner (Greedy or DP)
    # 5. Return a combined PlanningResult
    ```

### **Phase 3: Routing & Caching**
**File:** `routing/service.py` -> `routing/providers.py`
*   **Role:** Efficiency & Reliability.
*   **Logic:**
    -   **Adapter Pattern:** The `RoutingService` uses an abstract `BaseRoutingProvider`. This allows swapping between `osrm`, `ors`, or `offline` modes without changing core logic.
    -   **Split Caching:** Crucially, it caches only the **Route Object** (the road points), not the fuel plan. This ensures that if vehicle parameters (MPG, range) change, the road data is fast but the math is always accurate.

### **Phase 4: Station Discovery (Corridor Search)**
**File:** `fuelstations/repository.py`
*   **Role:** Performance at Scale.
*   **Performance Optimization:** 
    -   Uses a **Composite Index** on (Latitude, Longitude) in the database.
    -   Performs a **Bounding Box Query** (min/max lat/lng) to shrink the search space from 8,000+ stations down to ~100-200.
    -   Performs **In-Memory Projection** using `planner/geo.py` to filter stations within exactly 30km of the road path.

### **Phase 5: Refueling Optimization**
**File:** `planner/greedy.py` | `planner/dp.py`
*   **Role:** Cost Minimization.
*   **Greedy Logic (Default):** 
    -   At current station $S$, look ahead for the next 500 miles.
    -   If a cheaper station exists, buy exactly enough fuel to reach the *first* cheaper station.
    -   If $S$ is the cheapest in range, fill the tank completely.
    -   **Complexity:** $O(N \log N)$ - extremely fast.
*   **DP Logic (Reference):**
    -   Sweeps the route and splits it into segments where the set of reachable stations changes.
    -   Solves for the true mathematical optimum.
    -   Used to verify the correctness of the Greedy algorithm.

---

## 2. Key Data Models

### **FuelStation (`fuelstations/models.py`)**
Stores the imported CSV data with added coordinates.
*   `opis_id`: Unique identifier from the dataset.
*   `retail_price`: Decimal field for accuracy.
*   `geocode_status`: Tracks if the station has valid coordinates (OK, APPROXIMATE, or FAILED).
*   **Indexes:** `station_lat_lng_idx` (Essential for speed).

---

## 3. Performance & Scaling Features

1.  **Out-of-Band Geocoding:** Geocoding is slow (rate-limited). By moving it to a management command (`geocode_stations`), we ensure the API itself never has to wait for Nominatim.
2.  **Stateless Orchestration:** The logic in `api/services.py` has no dependency on the database directly (it uses the Repository), making it easily unit-testable.
3.  **Memory Efficiency:** Instead of loading thousands of full Django Model instances, the `StationRepository` uses `.values()` to only fetch the 5 fields needed for calculation, drastically reducing RAM usage.

---

## 4. Design Patterns Applied

| Pattern | Usage |
| :--- | :--- |
| **Adapter** | Decoupling external APIs (OSRM, Census, Nominatim). |
| **Strategy** | Switching between refueling algorithms (Greedy vs DP). |
| **Repository** | Isolating database queries from business logic. |
| **Factory** | Instantiating the correct Planner based on user input. |

---
*Created on: Wednesday, 10 June 2026*
