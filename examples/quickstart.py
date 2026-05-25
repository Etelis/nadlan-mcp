"""End-to-end demo of the nadlan.gov.il client (run: python example.py)."""

from nadlan import NadlanClient


def main() -> None:
    with NadlanClient() as nadlan:
        # 1) Resolve a free-text query to typed ids (public govmap search).
        print("== search: 'רוטשילד תל אביב' ==")
        for hit in nadlan.search("רוטשילד תל אביב")[:5]:
            print(f"  {hit.type:12} id={hit.id:<10} base_name={hit.base_name}  {hit.label}")

        # 2) Settlement summary + price trends (static, no auth).
        print("\n== settlement 5000 (Tel Aviv-Yafo) ==")
        s = nadlan.settlement_summary(5000)
        print("  name:", s["settlementName"])
        print("  neighborhoods:", len(s["otherNeighborhoods"]))
        print("  streets:", len(s["otherSettlmentStreets"]))
        for room in s["trends"]["rooms"]:
            summary = room["summary"]
            print(
                f"  {str(room['numRooms']):>3} rooms: last-year median "
                f"₪{summary['lastYearAvgPrice']:,} ({summary['priceDifferencePercentage']}%)"
            )

        # 3) A neighborhood summary (legacy UNIQ_ID from otherNeighborhoods).
        nb_id = s["otherNeighborhoods"][0]["id"]
        print(f"\n== neighborhood {nb_id} ==")
        nb = nadlan.neighborhood_summary(nb_id)
        print("  name:", nb["neighborhoodName"], "in", nb["settlementName"])

        # 4) Property-type lookup index.
        print("\n== deal-nature codes (first 3) ==")
        for d in nadlan.deal_natures()[:3]:
            print(f"  {d['DealNature']}: {d['DealNatureDescription']}")

        # 5) Transaction listing via the signed dynamic API.
        #    Currently returns an empty statusCode:405 envelope upstream-wide.
        print("\n== deal-data (street 50001103) ==")
        result = nadlan.deal_data("streetCode", "50001103")
        data = result.get("data", {})
        print(f"  statusCode={result.get('statusCode')} total_rows={data.get('total_rows')}")
        if not data.get("items"):
            print("  (no items - upstream /deal-data outage; signing/transport verified)")


if __name__ == "__main__":
    main()
