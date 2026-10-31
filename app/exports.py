from io import BytesIO, StringIO
import csv
from decimal import Decimal
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

def safe(v):
    return "'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v

def export(data,currency='HTB',xlsx=True):
    rate=Decimal(data['rate']['rate']) if currency=='CNY' and data['rate'] else Decimal(1)
    if currency=='CNY' and not data['rate']: raise ValueError('暂无可用人民币参考汇率')
    def money(v): return float((Decimal(str(v))*rate).quantize(Decimal('.01'))) if v is not None else None
    cols=['网站原始时间','北京时间','类型','昵称','作品','章节','原始海棠币文本','海棠币金额','展示金额','展示单位','请款状态']
    tx=lambda rs:[[r['raw_time'],r['time'],r['kind'],r['nickname'],r['work_name'],r['chapter_name'],r['raw_amount'],r['amount'],money(r['amount']),'人民币' if currency=='CNY' else '海棠币',r['status']] for r in rs]
    tables=[('稿费明细',cols,tx(data['transactions'])),('请款明细',cols,tx(data['withdrawals'])),
      ('每日汇总',['日期','海棠币收入','展示收入','交易笔数','平均单笔海棠币','展示平均单笔','7日移动平均海棠币','展示7日移动平均','当天未结束'],[[r['date'],r['amount'],money(r['amount']),r['count'],r['average'],money(r['average']),r['ma'],money(r['ma']),r['unfinished']] for r in data['daily']]),
      ('小时汇总',['小时','海棠币合计','展示合计','交易笔数','海棠币小时均值','展示小时均值','平均笔数'],[[r['hour'],r['amount'],money(r['amount']),r['count'],r['mean_amount'],money(r['mean_amount']),r['mean_count']] for r in data['hours']]),
      ('昵称贡献',['昵称','海棠币收入','展示收入','笔数','占比'],[[r['name'],r['amount'],money(r['amount']),r['count'],r['share']] for r in data['readers']]),
      ('作品汇总',['作品','海棠币收入','展示收入','笔数','占比','海棠币日均','展示日均'],[[r['name'],r['amount'],money(r['amount']),r['count'],r['share'],r['average'],money(r['average'])] for r in data['ranking']])]
    if not xlsx:
        out=StringIO(); writer=csv.writer(out); writer.writerow(cols+['TWD/CNY参考汇率','汇率数据时间'])
        for row in tables[0][2]: writer.writerow([safe(v) for v in row]+[str(rate) if currency=='CNY' else '',data['rate']['time'] if data['rate'] else ''])
        return ('\ufeff'+out.getvalue()).encode('utf-8')
    wb=Workbook(); wb.remove(wb.active)
    for title,headers,rows in tables:
        ws=wb.create_sheet(title); ws.append(headers)
        for row in rows: ws.append([safe(v) for v in row])
        ws.freeze_panes='A2'; ws.auto_filter.ref=ws.dimensions
        for cell in ws[1]: cell.fill=PatternFill('solid',fgColor='766399'); cell.font=Font(color='FFFFFF',bold=True)
        for i,col in enumerate(ws.columns,1):
            from openpyxl.utils import get_column_letter
            ws.column_dimensions[get_column_letter(i)].width=min(44,max(14,max(len(str(c.value or '')) for c in col[:200])+2))
        for row in ws.iter_rows(min_row=2):
            for c in row:
                if isinstance(c.value,float): c.number_format='0.00000'
    ws=wb.create_sheet('口径与汇率')
    for row in [['项目','说明'],['所选范围',f"{data['range']['start']} 至 {data['range']['end']}"],['原始货币','海棠币；按用户约定1海棠币=1TWD'],['展示货币',currency],['TWD/CNY参考汇率',str(rate) if currency=='CNY' else '未换算'],['汇率数据时间',data['rate']['time'] if data['rate'] else '无'],['汇率来源',data['rate']['source'] if data['rate'] else '无'],['换算口径','全部历史统一按该参考汇率估值，非实际提现到账'],['最近成功同步',data['cutoff']],['历史覆盖起点',data['coverage_start']],['账号财务','请款明细为账号总览，不随作品及日期筛选'],['平均值','排除当天，已验证范围内的无收入完整日期计零'],['匿名昵称','同名与匿名昵称可能对应多人']]: ws.append(row)
    ws.column_dimensions['A'].width=24; ws.column_dimensions['B'].width=90
    out=BytesIO(); wb.save(out); return out.getvalue()
