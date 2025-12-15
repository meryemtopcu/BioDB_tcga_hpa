from flask import Flask, render_template, request, redirect, url_for
from flaskext.mysql import MySQL
import yaml
import time


app = Flask(
    __name__,
    static_folder="static",      # static folder
    static_url_path="/static"    # URL for static
)


#---- DB Config from YAML ---------------------------------------------
db_config = yaml.load(open('db.yaml'), Loader=yaml.FullLoader)

app.config['MYSQL_DATABASE_HOST'] = db_config['mysql_host']
app.config['MYSQL_DATABASE_USER'] = db_config['mysql_user']
app.config['MYSQL_DATABASE_PASSWORD'] = db_config['mysql_password']
app.config['MYSQL_DATABASE_DB'] = db_config['mysql_db']

mysql = MySQL()
mysql.init_app(app)

# ===========HELPERS==============================================================================================================================================================
# --- HPA sample rows for home page table ----------------------------------------------------------------
def get_hpa_sample(limit=10):
    conn = mysql.connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            gene_id,          -- 0
            gene_name,        -- 1
            cancer,           -- 2
            high,             -- 3
            medium,           -- 4
            low,              -- 5
            not_detected      -- 6 
        FROM hpa
        LIMIT %s;
    """, (limit,))

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


# --- TCGA sample rows for home page table -------------------------------------------------------------------
def get_tcga_sample(limit=10):
    conn = mysql.connect()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            sample_id,          -- 0
            gene_id,            -- 1
            gene_name,          -- 2
            unstranded,         -- 3
            stranded_first,     -- 4
            stranded_second,    -- 5
            tpm_unstranded,     -- 6
            fpkm_unstranded,    -- 7
            fpkm_uq_unstranded  -- 8
        FROM tcga
        LIMIT %s;
    """, (limit,))

    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows



# --------------------------------------------------------------------------------------------------------------------
# ---------- HELPERS -  SEARCH ON HPA TABLE -------------------------------------------------------------------------
def get_hpa_by_gene_id(gene_id):
    """
    Return 1 row from HPA for a given gene_id.
    """
    conn = mysql.connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT gene_id, gene_name, cancer,
               high, medium, low, not_detected
        FROM hpa
        WHERE gene_id = %s
        LIMIT 1
        """,
        (gene_id,),
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


# ---------- HELPERS - SEARCH ON TCGA TABLE -------------------------------------------------------------------------
def get_tcga_rows_by_gene_id(gene_id):
    """
    Return ALL TCGA rows for a given gene_id (one or more rows per sample).
    """
    conn = mysql.connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT sample_id, gene_id, gene_name,
               unstranded, stranded_first, stranded_second,
               tpm_unstranded, fpkm_unstranded, fpkm_uq_unstranded
        FROM tcga
        WHERE gene_id = %s
        ORDER BY sample_id
        """,
        (gene_id,),
    )
    rows = cur.fetchall()  # many rows
    cur.close()
    conn.close()
    return rows


# ---------- Resolve Gene_ids by entered gene name for resolve page --------------------------------------
def resolve_gene_ids_by_name(gene_name, limit=50):
    conn = mysql.connect()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT gene_id, gene_name
        FROM tcga
        WHERE gene_name = %s
        ORDER BY gene_id
        LIMIT %s;
    """, (gene_name, limit))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows



# ---------- HELPERS FOR GRAPHS -------------------------------------------------------------------------------------------------------------------------------
# ---------- CALCULATIONS FOR HPA GRAPH --------------------------------------------------------
def get_hpa_gene_level_counts():
    """
    Count how many DISTINCT genes have at least one entry with:
    - high > 0
    - medium > 0
    - low > 0
    - not_detected > 0

    Also return total number of DISTINCT genes in the HPA table.
    This matches the question: 
    "How many genes are high / medium / low / not detected?"
    """

    conn = mysql.connect()    # open MySQL connection
    cur = conn.cursor()       # create cursor to run SQL

    # One SELECT with conditional COUNTs using CASE.
    # We use DISTINCT gene_id so we count genes, not rows.
    cur.execute("""
        SELECT
            COUNT(DISTINCT gene_id) AS total_genes,

            COUNT(DISTINCT CASE WHEN high > 0 THEN gene_id END) AS high_genes,
            COUNT(DISTINCT CASE WHEN medium > 0 THEN gene_id END) AS medium_genes,
            COUNT(DISTINCT CASE WHEN low > 0 THEN gene_id END) AS low_genes,
            COUNT(DISTINCT CASE WHEN not_detected > 0 THEN gene_id END) AS not_detected_genes

        FROM hpa
        -- optional: WHERE cancer = 'breast cancer'
        -- for now all rows are breast cancer, so the WHERE is not strictly needed
    """)

    row = cur.fetchone()
    cur.close()
    conn.close()

    # row is a tuple: (total_genes, high_genes, medium_genes, low_genes, not_detected_genes)
    return {
        "total_genes": row[0] or 0,
        "high_genes": row[1] or 0,
        "medium_genes": row[2] or 0,
        "low_genes": row[3] or 0,
        "not_detected_genes": row[4] or 0,
    }

# ---------- CALCULATIONS FOR TCGA GRAPH -------------------------------------------------------------------
import json  # to pass Python lists/dicts into JavaScript safely as JSON.

def get_tcga_duplicate_overview(limit=25):
    """
    Returns ONE row per sample_id. Output columns (per sample_id):
      1) n_genes_not_repeated  : # of distinct gene_id that appear exactly ONCE in that sample
      2) n_genes_repeated_twice: # of distinct gene_id that appear exactly TWICE in that sample
      3) n_distinct_genes      : total # of distinct gene_id in that sample

    Strategy:
    1) First pick only N sample_id values (LIMIT %s).
    2) Then compute gene_count only for those samples. This avoids scanning/grouping the whole tcga table for /stats.

     Performance idea:
    - We do NOT summarize the whole TCGA table.
    - We first pick only N sample_ids (preview).
    - Then we compute counts only for those sample_ids.

    Returns:
      List of tuples: (sample_id, n_genes_not_repeated, n_genes_repeated_twice, n_distinct_genes)
    """

    conn = mysql.connect()
    cur = conn.cursor()
    # ------------------------------------------------------------------------------------------
    # QUERY #1: Pick a small list of sample_id (preview list)
    # - DISTINCT removes duplicates
    # - ORDER  stable/reproducible output
    # - LIMIT reduces work for the expensive aggregation query later
    # ------------------------------------------------------------------------------------------
    t0 = time.time()
    cur.execute("""
        SELECT DISTINCT sample_id
        FROM tcga
        ORDER BY sample_id
        LIMIT %s;
    """, (limit,))

    # fetchall() returns list of tuples like: [('S1',), ('S2',), ...]
    sample_rows = cur.fetchall()
    t1 = time.time()

    # Convert list of 1-column tuples into a plain Python list: ['S1', 'S2', ...]
    sample_ids = [r[0] for r in sample_rows]

    # If no samples exist, return empty result (avoid SQL errors later)
    if not sample_ids:
        cur.close()
        conn.close()
        return []

# ------------------------------------------------------------------------------------------
    # QUERY #2: Compute the overview only for selected sample_ids
    #
    # Key trick:
    # - For IN (%s, %s, %s ...) we must generate the correct number of placeholders.
    # - Never do string interpolation for values. Use placeholders to stay safe.
    # ------------------------------------------------------------------------------------------
    placeholders = ",".join(["%s"] * len(sample_ids))  # e.g. "%s,%s,%s" for 3 ids

    sql = f"""
        SELECT
          sample_id,
          SUM(gene_count = 1) AS n_genes_not_repeated,
          SUM(gene_count = 2) AS n_genes_repeated_twice,
          COUNT(*)            AS n_distinct_genes
        FROM (
          SELECT
            sample_id,
            gene_id,
            COUNT(*) AS gene_count
          FROM tcga
          WHERE sample_id IN ({placeholders})
          GROUP BY sample_id, gene_id
        ) gene_counts
        GROUP BY sample_id
        ORDER BY sample_id;
    """

    # Execute query with all selected sample_ids as parameters
    cur.execute(sql, tuple(sample_ids))
    rows = cur.fetchall()
    t2 = time.time()

    print("TCGA Q1 (sample list):", round(t1 - t0, 3), "sec")
    print("TCGA Q2 (aggregation):", round(t2 - t1, 3), "sec")


    # 2) Cleanup
    cur.close()
    conn.close()

    # 3) Return final overview rows
    return rows

def get_tcga_tpm_by_sample_for_gene_id(gene_id):
    """
        Returns two lists for chart:
            labels: [sample_id, ...]
            values: [mean_tpm_unstranded_per_sample, ...]
    Handles duplicates by averaging.
    """
    conn = mysql.connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT sample_id, tpm_unstranded
        FROM tcga
        WHERE gene_id = %s
        ORDER BY sample_id
        """,
        (gene_id,),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    # group by sample_id
    sums = {}
    counts = {}
    for sample_id, tpm in rows:
        tpm_val = float(tpm) if tpm is not None else 0.0
        sums[sample_id] = sums.get(sample_id, 0.0) + tpm_val
        counts[sample_id] = counts.get(sample_id, 0) + 1

    labels = list(sums.keys())
    values = [sums[s] / counts[s] for s in labels]
    return labels, values

   
# =========================================================================================================================================================================



# =====ROUTES====================================================================================================================================================================


# ---- HOME PAGE ---------------------------------------------------------------------------------------
@app.route("/")
def home():
    
    hpa_gene_stats = get_hpa_gene_level_counts() # --- Left panel HPA overview 
    tcga_dup_rows = get_tcga_duplicate_overview() # --- Right panel: TCGA overview
    hpa_rows = get_hpa_sample(limit=10) # --- Two small sample tables at the bottom 
    tcga_rows = get_tcga_sample(limit=10) # --- Two small sample tables at the bottom 

    return render_template(
        "home.html", active_page="home",
        hpa_gene_stats=hpa_gene_stats,
        tcga_dup_rows=tcga_dup_rows,
        hpa_rows=hpa_rows,
        tcga_rows=tcga_rows,
    )




# ---- RESULTS PAGE ---------------------------------------------------------------------------------------
@app.route("/results")
def results():
    # 1) Read gene_id from the URL query string.
    #    Example: /results?gene_id=ENSG00000141510
    gene_id = request.args.get("gene_id", "").strip()

    # 2) If gene_id is missing/empty, go back to the home page.
    if not gene_id:
        return redirect(url_for("home"))

    # 3) Query both data sources using the SAME stable identifier (gene_id).
    hpa_row = get_hpa_by_gene_id(gene_id)  #    - HPA: returns one row (gene-level protein summary)
    tcga_rows = get_tcga_rows_by_gene_id(gene_id) #  TCGA: returns many rows (one row per sample, sometimes duplicates)

    # 4) If there is no data in BOTH tables, still render results.html,
    #    but send empty values to avoid "undefined" errors in the template.
    if (hpa_row is None) and (len(tcga_rows) == 0):
        return render_template(
            "results.html",
            gene_id=gene_id,
            gene_name=None,
            hpa=None,
            tcga_rows=[],
            hpa_chart=None,
            tcga_chart=None
        )

    # 5) Decide which gene_name to display.
    #    Prefer HPA gene_name if available, otherwise take gene_name from the first TCGA row.
    gene_name = hpa_row[1] if hpa_row else tcga_rows[0][2]

    # 6) Build chart data for HPA (single bar chart).
    #    If HPA is missing, keep hpa_chart=None so the template can hide that chart.
    hpa_chart = None
    if hpa_row is not None:
        hpa_chart = {
            "labels": ["High", "Medium", "Low", "Not detected"],
            "values": [
                hpa_row[3] or 0,  # high
                hpa_row[4] or 0,  # medium
                hpa_row[5] or 0,  # low
                hpa_row[6] or 0   # not_detected
            ]
        }

    # 7) Build chart data for TCGA (TPM per sample).
    #    The helper handles duplicates by aggregating (e.g., mean TPM per sample).
    tcga_chart = None
    labels, values = get_tcga_tpm_by_sample_for_gene_id(gene_id)
    if labels:  # if we have at least one sample
        tcga_chart = {
            "labels": labels,   # sample_ids
            "values": values    # TPM values aligned with labels
        }

    # 8) Render the results page with:
    #    - raw table data (hpa_row, tcga_rows)
    #    - chart-ready JSON-like dicts (hpa_chart, tcga_chart)
    return render_template(
        "results.html",
        gene_id=gene_id,
        gene_name=gene_name,
        hpa=hpa_row,
        tcga_rows=tcga_rows,
        hpa_chart=hpa_chart,
        tcga_chart=tcga_chart
    )


# ---- RESOLVE PAGE ---------------------------------------------------------------------------------------
@app.route("/resolve")
def resolve():
    # 1) Read gene_name parameter from the URL
    #    Example: /resolve?gene_name=TP53
    #    strip() removes leading/trailing whitespace
    gene_name = request.args.get("gene_name", "").strip()

    # 2) If no gene name was provided, redirect back to home
    if not gene_name:
        return redirect(url_for("home"))

    # 3) Core conversion step:
    #    Convert gene symbol (e.g. TP53) into one or more stable gene identifiers (ENSG...)
    #    The database lookup may return:
    #    - 0 matches  -> unknown gene symbol
    #    - 1 match    -> unambiguous mapping
    #    - >1 matches -> ambiguous symbol, user must choose
    candidates = resolve_gene_ids_by_name(gene_name)

    # 4) No matching gene_id found → go back to home
    if len(candidates) == 0:
        return redirect(url_for("home"))

    # 5) Exactly one gene_id found → skip resolve page
    #    Redirect directly to the results page for that gene_id
    if len(candidates) == 1:
        gene_id = candidates[0][0]  # first element of tuple is gene_id
        return redirect(url_for("results", gene_id=gene_id))

    # 6) Multiple gene_ids found → show resolve page
    #    Let the user select the correct gene_id
    return render_template(
        "resolve.html",
        gene_name=gene_name,
        candidates=candidates
    )



# ---- ABOUT PAGE ---------------------------------------------------------------------------------------
@app.route("/about")
def about():
    return render_template("about.html", active_page="about")


# ---- HELP PAGE ----------------------------------------------------------------------------------------
@app.route("/help")
def help_page():
    return render_template("help.html", active_page="help")


# ---- CONTACT PAGE -------------------------------------------------------------------------------------
@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        gene = request.form.get("gene", "").strip()
        message = request.form.get("message", "").strip()

        # Minimum: logla ()
        app.logger.info("CONTACT: email=%s gene=%s message=%s", email, gene, message)

        # flash("Message received. Thank you!", "success")

        return redirect(url_for("contact"))

    return render_template("contact.html", active_page="contact")


if __name__ == "__main__":
    app.run(debug=True)
