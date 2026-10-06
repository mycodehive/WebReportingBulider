"""Fixed synthetic data; no user content or filesystem access."""
SALES_DEMO = 'sales-v1'


def sales_records(limit=65):
    names = ['department', 'customer', 'amount']
    rows = [{'department': f'영업 {index // 25 + 1}팀', 'customer': f'예제 고객 {index + 1:02d}',
             'amount': str(100000 + index * 2500)} for index in range(min(limit, 65))]
    return names, rows
