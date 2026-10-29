from datetime import date,datetime
import calendar
import config
from db import init_db,upsert_cutoff,add_snapshot

def parse_date(v): return datetime.strptime(v,'%Y-%m-%d').date()
def month_add(d,months=1):
    y=d.year+(d.month-1+months)//12; m=(d.month-1+months)%12+1
    return date(y,m,min(config.CAPITALIZATION_DAY,calendar.monthrange(y,m)[1]))
def calculate_balance(as_of=None,persist=False):
    as_of=as_of or config.now_colombia().date(); anchor=parse_date(config.BALANCE_ANCHOR_DATE)
    if anchor.day!=config.CAPITALIZATION_DAY: raise ValueError('BALANCE_ANCHOR_DATE debe caer el día 15.')
    if as_of<anchor: raise ValueError('La fecha consultada no puede ser anterior al corte ancla.')
    principal=float(config.BALANCE_ANCHOR_PRINCIPAL_COP); last_cutoff=anchor; next_cutoff=month_add(last_cutoff); cutoffs=[]
    while as_of>=next_cutoff:
        before=principal; interest=before*config.MONTHLY_RATE; after=before+interest
        cutoffs.append({'cutoff_date':next_cutoff,'principal_before':before,'monthly_rate':config.MONTHLY_RATE,'interest_capitalized':interest,'principal_after':after})
        principal=after; last_cutoff=next_cutoff; next_cutoff=month_add(last_cutoff)
    days=(as_of-last_cutoff).days
    daily_rate=config.MONTHLY_RATE/config.DAYS_IN_MONTH_BASIS
    accrued=principal*daily_rate*days
    total=principal+accrued
    result={'as_of':as_of,'principal':principal,'days_accrued':days,'daily_rate':daily_rate,'accrued_interest':accrued,'total_balance':total,'last_cutoff':last_cutoff,'next_cutoff':next_cutoff,'cutoffs':cutoffs}
    if persist:
        init_db()
        for x in cutoffs: upsert_cutoff(x['cutoff_date'].isoformat(),x['principal_before'],x['monthly_rate'],x['interest_capitalized'],x['principal_after'])
        add_snapshot(as_of.isoformat(),principal,days,daily_rate,accrued,total,last_cutoff.isoformat(),next_cutoff.isoformat())
    return result
def current_balance(as_of=None): return calculate_balance(as_of,False)['total_balance']
def format_cop(v):
    s=f'{float(v):,.2f}'.replace(',','X').replace('.',',').replace('X','.'); return f'${s} COP'
def formatted_date(as_of=None): return (as_of or config.now_colombia().date()).strftime('%d/%m/%Y')
