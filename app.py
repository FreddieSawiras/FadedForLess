import streamlit as st

# ----------------------------------------------------------------------------
# PAGE CONFIG
# ----------------------------------------------------------------------------
st.set_page_config(
    page_title="FADEDFORLESS | Premium Barber",
    page_icon="💈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

INSTAGRAM_URL = "https://www.instagram.com/fadedforless/"

# Real, freely-usable photography (Unsplash) — not AI generated.
IMG_HERO = "https://images.unsplash.com/photo-1503951914875-452162b0f3f1?w=1600&q=80&auto=format&fit=crop"
IMG_ABOUT = "https://images.unsplash.com/photo-1593702275687-f8b402bf1fb5?w=1200&q=80&auto=format&fit=crop"
IMG_PRICE_10 = "https://images.unsplash.com/photo-1647140655214-e4a2d914971f?w=1000&q=80&auto=format&fit=crop"
IMG_PRICE_15 = "https://images.unsplash.com/photo-1567894340315-735d7c361db0?w=1000&q=80&auto=format&fit=crop"
IMG_STRIP_1 = "https://images.unsplash.com/photo-1585747860715-2ba37e788b70?w=800&q=80&auto=format&fit=crop"
IMG_STRIP_2 = "https://images.unsplash.com/photo-1621645582931-d1d3e6564943?w=800&q=80&auto=format&fit=crop"
IMG_STRIP_3 = "https://images.unsplash.com/photo-1536520002442-39764a41e987?w=800&q=80&auto=format&fit=crop"

# ----------------------------------------------------------------------------
# ROUTING (query params drive the "pages")
# ----------------------------------------------------------------------------
VALID_PAGES = ["Home", "About Me", "Pricing", "Instagram"]

qp = st.query_params
current_page = qp.get("page", "Home")
if current_page not in VALID_PAGES:
    current_page = "Home"

# ----------------------------------------------------------------------------
# GLOBAL CSS
# ----------------------------------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@500;600;700;800&family=Inter:wght@300;400;500;600;700&display=swap');

    :root{
        --gold:#D4AF37;
        --gold-light:#F1D98B;
        --gold-soft:rgba(212,175,55,0.15);
        --black:#070707;
        --charcoal:#121212;
        --charcoal-2:#181818;
        --charcoal-3:#1f1f1f;
        --text-muted:#b8b3a8;
    }

    /* ---------- HIDE STREAMLIT CHROME ---------- */
    #MainMenu {visibility:hidden;}
    footer {visibility:hidden;}
    header[data-testid="stHeader"]{
        background:transparent;
        height:0;
    }
    div[data-testid="stToolbar"]{display:none;}
    div[data-testid="stDecoration"]{display:none;}
    div[data-testid="stStatusWidget"]{display:none;}
    #stDecoration{display:none;}
    .stDeployButton{display:none;}

    /* ---------- BASE ---------- */
    html, body, [class*="css"]{
        font-family:'Inter', sans-serif;
    }
    .stApp{
        background:
            radial-gradient(circle at 15% 0%, rgba(212,175,55,0.06), transparent 40%),
            radial-gradient(circle at 85% 20%, rgba(212,175,55,0.05), transparent 35%),
            var(--black);
        color:#EDEAE2;
    }
    .block-container{
        padding-top:0rem;
        padding-bottom:0rem;
        max-width:100%;
    }
    h1,h2,h3,h4{
        font-family:'Playfair Display', serif;
        color:#F5F1E6;
        letter-spacing:0.5px;
    }
    p, span, li{
        font-family:'Inter', sans-serif;
        color:var(--text-muted);
        line-height:1.7;
    }
    a{ text-decoration:none; }
    hr{ border-color: rgba(212,175,55,0.2); }

    .gold{ color:var(--gold); }
    .gold-grad{
        background: linear-gradient(120deg, var(--gold-light), var(--gold) 55%, #a67c1f);
        -webkit-background-clip:text;
        background-clip:text;
        color:transparent;
    }

    /* ---------- NAVBAR ---------- */
    .navbar-wrap{
        position:sticky;
        top:0;
        z-index:999;
        background:rgba(7,7,7,0.85);
        backdrop-filter:blur(10px);
        -webkit-backdrop-filter:blur(10px);
        border-bottom:1px solid rgba(212,175,55,0.25);
    }
    .navbar{
        max-width:1200px;
        margin:0 auto;
        display:flex;
        align-items:center;
        justify-content:space-between;
        padding:18px 32px;
        flex-wrap:wrap;
    }
    .brand{
        font-family:'Playfair Display', serif;
        font-weight:800;
        font-size:1.5rem;
        letter-spacing:2px;
        color:#F5F1E6;
    }
    .brand span{ color:var(--gold); }
    .nav-links{
        display:flex;
        gap:38px;
        align-items:center;
    }
    .nav-link{
        position:relative;
        font-size:0.92rem;
        font-weight:600;
        letter-spacing:1.2px;
        text-transform:uppercase;
        color:#D9D4C7;
        padding:6px 2px;
        transition:color 0.25s ease;
    }
    .nav-link::after{
        content:"";
        position:absolute;
        left:0;
        bottom:-4px;
        width:100%;
        height:2px;
        background:linear-gradient(90deg, var(--gold-light), var(--gold));
        transform:scaleX(0);
        transform-origin:left;
        transition:transform 0.3s cubic-bezier(.4,0,.2,1);
    }
    .nav-link:hover{ color:var(--gold-light); }
    .nav-link:hover::after{ transform:scaleX(1); }
    .nav-link.active{ color:var(--gold); }
    .nav-link.active::after{ transform:scaleX(1); }

    /* ---------- BUTTONS ---------- */
    .btn{
        display:inline-block;
        padding:14px 34px;
        font-size:0.85rem;
        font-weight:700;
        letter-spacing:1.5px;
        text-transform:uppercase;
        border-radius:2px;
        transition:all 0.3s ease;
        cursor:pointer;
        border:1px solid transparent;
    }
    .btn-primary{
        background:linear-gradient(120deg, var(--gold-light), var(--gold));
        color:#0a0a0a !important;
        box-shadow:0 8px 24px rgba(212,175,55,0.25);
    }
    .btn-primary:hover{
        transform:translateY(-2px);
        box-shadow:0 12px 30px rgba(212,175,55,0.4);
        filter:brightness(1.05);
    }
    .btn-outline{
        background:transparent;
        color:var(--gold-light) !important;
        border:1px solid rgba(212,175,55,0.6);
    }
    .btn-outline:hover{
        background:rgba(212,175,55,0.1);
        border-color:var(--gold);
        transform:translateY(-2px);
    }

    /* ---------- HERO ---------- */
    .hero{
        position:relative;
        min-height:88vh;
        display:flex;
        align-items:center;
        overflow:hidden;
        border-bottom:1px solid rgba(212,175,55,0.2);
    }
    .hero-bg{
        position:absolute;
        inset:0;
        background-image:linear-gradient(100deg, rgba(7,7,7,0.96) 30%, rgba(7,7,7,0.55) 65%, rgba(7,7,7,0.25) 100%), url('__IMG_HERO__');
        background-size:cover;
        background-position:center 30%;
    }
    .hero-content{
        position:relative;
        z-index:2;
        max-width:1200px;
        margin:0 auto;
        padding:0 32px;
        width:100%;
    }
    .eyebrow{
        letter-spacing:4px;
        text-transform:uppercase;
        color:var(--gold);
        font-size:0.78rem;
        font-weight:700;
        margin-bottom:18px;
        display:flex;
        align-items:center;
        gap:12px;
    }
    .eyebrow::before{
        content:"";
        width:36px;
        height:1px;
        background:var(--gold);
        display:inline-block;
    }
    .hero-title{
        font-size:5rem;
        line-height:1.02;
        font-weight:800;
        margin:0 0 20px 0;
        max-width:800px;
    }
    .hero-tagline{
        font-size:1.35rem;
        color:#E8E3D6;
        font-weight:500;
        max-width:620px;
        margin-bottom:14px;
        font-family:'Playfair Display', serif;
        font-style:italic;
    }
    .hero-desc{
        font-size:1.02rem;
        max-width:560px;
        margin-bottom:38px;
    }
    .hero-btns{ display:flex; gap:18px; flex-wrap:wrap; }

    /* ---------- SECTION SHELL ---------- */
    .section{
        max-width:1200px;
        margin:0 auto;
        padding:100px 32px;
    }
    .section-tight{ padding:70px 32px; }
    .section-head{ margin-bottom:56px; }
    .section-head .eyebrow{ justify-content:flex-start; }
    .section-title{ font-size:2.6rem; margin-bottom:14px; }
    .section-sub{ max-width:600px; font-size:1.05rem; }
    .divider{
        width:70px;
        height:2px;
        background:linear-gradient(90deg, var(--gold), transparent);
        margin:20px 0 0 0;
    }

    /* ---------- ABOUT ---------- */
    .about-wrap{
        display:grid;
        grid-template-columns:1.05fr 1fr;
        gap:70px;
        align-items:center;
    }
    .about-img-frame{
        position:relative;
        border:1px solid rgba(212,175,55,0.35);
        padding:14px;
        border-radius:4px;
    }
    .about-img-frame img{
        width:100%;
        display:block;
        border-radius:2px;
        filter:grayscale(15%) contrast(1.05);
    }
    .about-quote{
        font-family:'Playfair Display', serif;
        font-style:italic;
        font-size:1.28rem;
        color:#F1EADB;
        line-height:1.65;
        border-left:2px solid var(--gold);
        padding-left:26px;
        margin:26px 0 30px 0;
    }
    .pillars{
        display:grid;
        grid-template-columns:1fr 1fr;
        gap:16px;
        margin-top:10px;
    }
    .pillar{
        background:var(--charcoal-2);
        border:1px solid rgba(212,175,55,0.15);
        border-radius:6px;
        padding:16px 18px;
        font-size:0.92rem;
        color:#E9E4D6;
        font-weight:500;
        transition:border-color 0.25s ease, transform 0.25s ease;
    }
    .pillar:hover{
        border-color:rgba(212,175,55,0.55);
        transform:translateY(-3px);
    }
    .pillar b{ color:var(--gold); }

    /* ---------- PRICING ---------- */
    .price-grid{
        display:grid;
        grid-template-columns:1fr 1.12fr;
        gap:34px;
        align-items:stretch;
    }
    .price-card{
        background:linear-gradient(180deg, var(--charcoal-2), var(--charcoal));
        border:1px solid rgba(212,175,55,0.22);
        border-radius:10px;
        overflow:hidden;
        display:flex;
        flex-direction:column;
        transition:transform 0.3s ease, box-shadow 0.3s ease, border-color 0.3s ease;
        position:relative;
    }
    .price-card:hover{
        transform:translateY(-6px);
        box-shadow:0 22px 45px rgba(0,0,0,0.45);
        border-color:rgba(212,175,55,0.55);
    }
    .price-card.featured{
        border:1px solid rgba(212,175,55,0.75);
        box-shadow:0 0 0 1px rgba(212,175,55,0.15), 0 25px 60px rgba(212,175,55,0.12);
    }
    .price-card-img{
        height:230px;
        background-size:cover;
        background-position:center;
        position:relative;
    }
    .price-card-img::after{
        content:"";
        position:absolute; inset:0;
        background:linear-gradient(180deg, rgba(7,7,7,0.05), var(--charcoal-2) 96%);
    }
    .badge{
        position:absolute;
        top:18px; right:18px;
        background:linear-gradient(120deg, var(--gold-light), var(--gold));
        color:#0a0a0a;
        font-size:0.68rem;
        font-weight:800;
        letter-spacing:1.5px;
        text-transform:uppercase;
        padding:7px 14px;
        border-radius:20px;
        z-index:2;
        box-shadow:0 6px 16px rgba(0,0,0,0.35);
    }
    .price-card-body{
        padding:32px 30px 34px 30px;
        flex:1;
        display:flex;
        flex-direction:column;
    }
    .price-name{
        text-transform:uppercase;
        letter-spacing:2px;
        font-size:0.82rem;
        color:var(--gold);
        font-weight:700;
        margin-bottom:10px;
    }
    .price-amount{
        font-family:'Playfair Display', serif;
        font-size:3.2rem;
        font-weight:700;
        color:#F7F3E7;
        margin-bottom:4px;
        line-height:1;
    }
    .price-meta{
        display:flex;
        gap:14px;
        margin:14px 0 20px 0;
        flex-wrap:wrap;
    }
    .chip{
        border:1px solid rgba(212,175,55,0.35);
        color:#E9E4D6;
        font-size:0.78rem;
        font-weight:600;
        letter-spacing:0.5px;
        padding:6px 14px;
        border-radius:20px;
        background:rgba(212,175,55,0.06);
    }
    .price-desc{ font-size:0.98rem; margin-bottom:22px; }
    .price-line{
        margin-top:auto;
        padding-top:18px;
        border-top:1px solid rgba(212,175,55,0.15);
        font-size:0.85rem;
        color:var(--text-muted);
        font-style:italic;
    }

    /* ---------- IMAGE STRIP ---------- */
    .strip{
        display:grid;
        grid-template-columns:repeat(3, 1fr);
        gap:20px;
    }
    .strip img{
        width:100%;
        height:230px;
        object-fit:cover;
        border-radius:6px;
        border:1px solid rgba(212,175,55,0.18);
        filter:grayscale(20%) contrast(1.05);
        transition:filter 0.3s ease, transform 0.3s ease;
    }
    .strip img:hover{
        filter:grayscale(0%) contrast(1.1);
        transform:scale(1.02);
    }

    /* ---------- INSTAGRAM ---------- */
    .insta-panel{
        text-align:center;
        max-width:720px;
        margin:0 auto;
        padding:80px 40px;
        background:
            radial-gradient(circle at 50% 0%, rgba(212,175,55,0.08), transparent 60%),
            var(--charcoal-2);
        border:1px solid rgba(212,175,55,0.25);
        border-radius:14px;
    }
    .insta-icon{
        width:70px; height:70px;
        margin:0 auto 26px auto;
        border-radius:18px;
        background:linear-gradient(45deg,#f9ce34,#ee2a7b,#6228d7);
        display:flex; align-items:center; justify-content:center;
        font-size:1.8rem;
        box-shadow:0 10px 26px rgba(0,0,0,0.4);
    }
    .insta-handle{
        font-family:'Playfair Display', serif;
        font-size:2.2rem;
        color:#F5F1E6;
        margin-bottom:10px;
    }
    .insta-sub{ margin-bottom:34px; }
    .btn-insta{
        display:inline-block;
        padding:16px 42px;
        font-size:0.9rem;
        font-weight:800;
        letter-spacing:2px;
        text-transform:uppercase;
        border-radius:3px;
        color:#0a0a0a !important;
        background:linear-gradient(120deg, var(--gold-light), var(--gold));
        box-shadow:0 10px 28px rgba(212,175,55,0.3);
        transition:all 0.3s ease;
    }
    .btn-insta:hover{
        transform:translateY(-3px);
        box-shadow:0 16px 36px rgba(212,175,55,0.45);
    }

    /* ---------- FOOTER ---------- */
    .footer{
        border-top:1px solid rgba(212,175,55,0.18);
        padding:40px 32px;
        text-align:center;
        color:#847f72;
        font-size:0.82rem;
        letter-spacing:1px;
    }
    .footer span{ color:var(--gold); }

    /* ---------- RESPONSIVE ---------- */
    @media (max-width: 900px){
        .hero-title{ font-size:3rem; }
        .about-wrap{ grid-template-columns:1fr; gap:36px; }
        .price-grid{ grid-template-columns:1fr; }
        .strip{ grid-template-columns:1fr; }
        .navbar{ flex-direction:column; gap:14px; align-items:flex-start; }
        .nav-links{ gap:22px; flex-wrap:wrap; }
        .section{ padding:60px 20px; }
        .pillars{ grid-template-columns:1fr; }
    }
    </style>
    """.replace("__IMG_HERO__", IMG_HERO),
    unsafe_allow_html=True,
)

# ----------------------------------------------------------------------------
# NAVBAR
# ----------------------------------------------------------------------------
def nav_class(name):
    return "nav-link active" if current_page == name else "nav-link"

navbar_html = f"""
<div class="navbar-wrap">
  <div class="navbar">
    <div class="brand">FADED<span>FOR</span>LESS</div>
    <div class="nav-links">
      <a class="{nav_class('Home')}" href="?page=Home">Home</a>
      <a class="{nav_class('About Me')}" href="?page=About Me">About Me</a>
      <a class="{nav_class('Pricing')}" href="?page=Pricing">Pricing</a>
      <a class="{nav_class('Instagram')}" href="?page=Instagram">Instagram</a>
    </div>
  </div>
</div>
"""
st.markdown(navbar_html, unsafe_allow_html=True)

# ----------------------------------------------------------------------------
# HOME PAGE
# ----------------------------------------------------------------------------
def render_home():
    st.markdown(
        f"""
        <div class="hero">
            <div class="hero-bg"></div>
            <div class="hero-content">
                <div class="eyebrow">Modern Barbering</div>
                <h1 class="hero-title">FADED<span class="gold-grad">FOR</span>LESS</h1>
                <div class="hero-tagline">Premium cuts. Fair prices. No unnecessary markup.</div>
                <p class="hero-desc">
                    The goal is simple — quality barbering at a price that actually makes sense.
                    Every client gets a clean, precise cut and a professional experience,
                    without paying for the markup that comes with it.
                </p>
                <div class="hero-btns">
                    <a class="btn btn-primary" href="?page=Pricing">View Pricing</a>
                    <a class="btn btn-outline" href="{INSTAGRAM_URL}" target="_blank">Instagram</a>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="section section-tight">
            <div class="section-head">
                <div class="eyebrow">The Craft</div>
                <h2 class="section-title">Precision, every single time</h2>
                <div class="divider"></div>
                <p class="section-sub">A closer look at the kind of work that goes into every appointment.</p>
            </div>
            <div class="strip">
                <img src="{IMG_STRIP_1}" />
                <img src="{IMG_STRIP_2}" />
                <img src="{IMG_STRIP_3}" />
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class="section section-tight" style="padding-top:0;">
            <div class="insta-panel">
                <div class="insta-icon">📷</div>
                <div class="insta-handle">@fadedforless</div>
                <p class="insta-sub">See the latest work, book your next cut, and follow along on Instagram.</p>
                <a class="btn-insta" href="{INSTAGRAM_URL}" target="_blank">Follow on Instagram</a>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ----------------------------------------------------------------------------
# ABOUT PAGE
# ----------------------------------------------------------------------------
def render_about():
    st.markdown(
        f"""
        <div class="section">
            <div class="section-head">
                <div class="eyebrow">About Me</div>
                <h2 class="section-title">Quality work, honest pricing</h2>
                <div class="divider"></div>
            </div>
            <div class="about-wrap">
                <div class="about-img-frame">
                    <img src="{IMG_ABOUT}" />
                </div>
                <div>
                    <div class="about-quote">
                        "I'm a barber focused on helping people look and feel their best without
                        charging crazy prices. I believe getting a clean haircut shouldn't have to
                        be expensive, which is why I keep my prices affordable while putting real
                        effort into every cut."
                    </div>
                    <p>
                        Every client walks in for a fresh cut and walks out with a full, professional
                        experience — sharp lines, clean fades, and genuine attention to detail. No
                        rushed appointments, no inflated prices for a basic service.
                    </p>
                    <div class="pillars">
                        <div class="pillar"><b>Affordable</b><br/>Pricing that respects your wallet</div>
                        <div class="pillar"><b>Precise</b><br/>Clean lines and sharp fades</div>
                        <div class="pillar"><b>Personal</b><br/>Every client gets full attention</div>
                        <div class="pillar"><b>Premium Feel</b><br/>A pro experience, fair price</div>
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ----------------------------------------------------------------------------
# PRICING PAGE
# ----------------------------------------------------------------------------
def render_pricing():
    st.markdown(
        f"""
        <div class="section">
            <div class="section-head">
                <div class="eyebrow">Pricing</div>
                <h2 class="section-title">Simple, honest pricing</h2>
                <div class="divider"></div>
                <p class="section-sub">Two straightforward options. No hidden add-ons, no inflated markup.</p>
            </div>
            <div class="price-grid">
                <div class="price-card">
                    <div class="price-card-img" style="background-image:url('{IMG_PRICE_10}');"></div>
                    <div class="price-card-body">
                        <div class="price-name">Fade or Trim</div>
                        <div class="price-amount">$10</div>
                        <div class="price-meta">
                            <span class="chip">30 min</span>
                            <span class="chip">Fade OR Trim</span>
                        </div>
                        <p class="price-desc">
                            Choose either a clean fade or a trim. Perfect for keeping your haircut
                            fresh without spending a lot.
                        </p>
                        <div class="price-line">One service per visit — fade or trim, not both.</div>
                    </div>
                </div>
                <div class="price-card featured">
                    <div class="badge">Most Popular</div>
                    <div class="price-card-img" style="background-image:url('{IMG_PRICE_15}');"></div>
                    <div class="price-card-body">
                        <div class="price-name">Full Haircut</div>
                        <div class="price-amount">$15</div>
                        <div class="price-meta">
                            <span class="chip">1 hour</span>
                            <span class="chip">Fade + Trim</span>
                        </div>
                        <p class="price-desc">
                            A complete haircut including a clean fade plus a trim for a full,
                            refreshed look.
                        </p>
                        <div class="price-line">The full service — fade and trim together.</div>
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ----------------------------------------------------------------------------
# INSTAGRAM PAGE
# ----------------------------------------------------------------------------
def render_instagram():
    st.markdown(
        f"""
        <div class="section" style="text-align:center;">
            <div class="section-head" style="text-align:center;">
                <div class="eyebrow" style="justify-content:center;">Stay Connected</div>
                <h2 class="section-title">Follow @fadedforless</h2>
                <div class="divider" style="margin-left:auto; margin-right:auto;"></div>
            </div>
            <div class="insta-panel">
                <div class="insta-icon">📷</div>
                <div class="insta-handle">@fadedforless</div>
                <p class="insta-sub">
                    Fresh cuts, before-and-afters, and booking updates — all posted on Instagram.
                    Follow along to see the latest work and stay up to date.
                </p>
                <a class="btn-insta" href="{INSTAGRAM_URL}" target="_blank">Follow on Instagram</a>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

# ----------------------------------------------------------------------------
# ROUTER
# ----------------------------------------------------------------------------
if current_page == "Home":
    render_home()
elif current_page == "About Me":
    render_about()
elif current_page == "Pricing":
    render_pricing()
elif current_page == "Instagram":
    render_instagram()

# ----------------------------------------------------------------------------
# FOOTER
# ----------------------------------------------------------------------------
st.markdown(
    """
    <div class="footer">
        FADED<span>FOR</span>LESS — Premium cuts. Fair prices.
    </div>
    """,
    unsafe_allow_html=True,
)

#.\.venv\Scripts\Activate.ps1; streamlit run app.py
#git add .; git commit -m "Update website"; git push