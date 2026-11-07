# Market inputs

The reported study uses 167 joint month-end observations from 2012-11-30 through 2026-09-29, yielding 166 month-to-month changes. The valuation curve is a separate snapshot dated 2026-10-21. The [data provenance](market_metadata.json) records download settings, date bounds, proxy weights, software versions and SHA-256 hashes.

Run the downloader from the repository root after installing the package.

```bash
python -m pension_ldi.market
```

The downloader retrieves the current source vintage and writes `data/market.csv`, `data/curve.csv` and `data/market_metadata.json`. The two CSVs and provider cache are local and excluded from version control. Source revisions and later distributions can change historical adjusted prices and file hashes. [yfinance project documentation](https://github.com/ranaroussi/yfinance)

| Sleeve | Market proxy |
| --- | --- |
| Public equity | 50% iShares S&P/TSX 60 ETF (`XIU.TO`) and 50% Vanguard S&P 500 ETF (`VFV.TO`). VFV is CAD-listed and retains its U.S. currency exposure. [XIU](https://www.blackrock.com/ca/investors/en/products/239832/ishares-sptsx-60-index-etf), [VFV](https://www.vanguard.ca/en/product/etf/equity/9563/vanguard-sp-500-index-etf) |
| Long bonds | iShares Core Canadian Long Term Bond ETF (`XLB.TO`). The underlying long-bond index can include corporate and provincial exposure alongside federal bonds. [XLB](https://www.blackrock.com/ca/investors/en/products/239489/ishares-canadian-long-term-bond-index-etf) |
| Real assets | 50% BMO Equal Weight REITs ETF (`ZRE.TO`) and 50% iShares Global Infrastructure ETF (`IGF`). These are liquid public exposures used as economic proxies. [ZRE](https://newsroom.bmo.com/2010-05-26-BMO-Financial-Group-Expands-ETF-Line-Up-To-30-With-Addition-Of-Eight-New-Funds), [IGF](https://www.blackrock.com/us/individual/products/239746/ishares-global-infrastructure-etf) |
| Private equity | Invesco Global Listed Private Equity ETF (`PSP`). Its public holdings and exchange-traded returns proxy exposure to listed PE businesses. [PSP](https://www.invesco.com/us/en/financial-products/etfs/invesco-global-listed-private-equity-etf.html) |
| Credit | iShares Core Canadian Corporate Bond ETF (`XCB.TO`), an investment-grade corporate proxy containing both rate and spread risk. [XCB](https://www.blackrock.com/ca/investors/en/products/239485/ishares-canadian-corporate-bond-index-etf) |
| CAD FX translation | Yahoo Finance `USDCAD=X` close in CAD per USD. Multiply adjusted USD prices of IGF and PSP by same-date spot before calculating returns. [Yahoo Finance USD/CAD](https://finance.yahoo.com/quote/USDCAD%3DX/) |
| GoC zero curve | Official Bank of Canada zero yields at 0.25, 1, 2, 5, 10, 15, 20, 25 and 30 years, used as continuously compounded decimals. [Daily zero curve](https://www.bankofcanada.ca/rates/interest-rates/bond-yield-curves/), [curve methodology](https://www.bis.org/publications/paper-25-zero-coupon-yield-curves-technical-documentation.pdf#page=22) |

The calibration uses the last date in each completed calendar month with all ETF closes, FX and curve points observed. The date must be within seven calendar days of month-end. It rejects missing calendar months and excludes the partial valuation month. Both 50/50 baskets rebalance monthly and chain arithmetic proxy returns into indices starting at 100. The joint sample begins in November 2012 because of the VFV listing. Close timestamps differ across markets and the BoC zero curve has a publication lag, so the panel is suitable for retrospective scenario calibration.

Public-market trading prices incorporate dividends and splits through Yahoo's adjusted-close convention. Listed proxy returns cannot capture actual private fund fees, cash flows, leverage, secondary discounts or appraisal timing. Any smoothing and desmoothing of the private sleeve is an illustrative transformation of this public proxy.
