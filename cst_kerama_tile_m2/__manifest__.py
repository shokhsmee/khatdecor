{
    "name": "Kerama Tile m² (Kafel)",
    "summary": "Compute a tile's surface area from its height and width and sell tiles by m².",
    "description": """
Kerama Tile m²
==============

Adds tile (kafel) dimension fields to products that are sold by square meter:

* **Tile Height (cm)** and **Tile Width (cm)** entered per product.
* **Area per piece (m²)** computed automatically as height × width / 10000.

The dimension fields only appear when the product's Unit of Measure is m²,
so non-tile products stay clean. The computed area is also shown on sale
order lines so salespeople can see the size of each tile they sell by m².
    """,
    "author": "Kerama City",
    "category": "Sales",
    "version": "19.0.1.0.0",
    "depends": ["product", "uom", "sale"],
    "data": [
        "views/product_views.xml",
        "views/sale_order_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
