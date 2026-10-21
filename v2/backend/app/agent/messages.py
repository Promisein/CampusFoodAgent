"""User-facing clarification wording, separate from diagnostic reason codes."""
ISSUE_TEXT={
    'currency_budget':'数据集只有1–4档价格等级，无法可靠换算人均金额。要改用最高价格等级，还是取消金额限制？',
    'live_availability':'我只有历史门店数据，无法确认现在营业、实时座位或预约。是否改为按历史数据推荐？',
    'dietary_guarantee':'评论和类别不能保证原料或过敏安全，请向餐厅核实。可以继续按类别推荐，但需要先明确取消这一保证条件。',
    'unverifiable_preference':'环境偏好可以参考评论，但无法保证一定满足。是否接受把它作为软偏好？',
    'ambiguous_preference':'这个偏好还不够具体：你更重视安静、正式环境、适合聚会，还是价格？也可以不限定菜系。',
    'conflict':'要求中存在冲突，例如同一类别同时被要求和排除。请说明保留哪一个条件。',
    'invalid_range':'目前支持0–50公里内的正半径、1–4档价格等级，请调整范围。',
    'location_change':'更换城市或位置请新建会话并填写城市与坐标，避免沿用错误位置。',
    'unknown_cuisine':'这类菜品还没有可靠的类别映射。可以改用中餐、日料、咖啡等类别，或明确接受关键词检索而不保证菜系。',
    'out_of_scope':'我主要帮助你找餐厅、比较当前结果和保存收藏。请告诉我用餐场景或餐饮需求。',
    'unsupported_constraint':'这个条件目前无法可靠核实。请说明它是必须满足的要求，还是可参考评论的偏好。',
}

LEGACY_CODES={
    'currency_budget_not_price_level':'currency_budget','current_hours_unavailable':'live_availability',
    'allergy_not_verifiable':'dietary_guarantee','dietary_guarantee_unavailable':'dietary_guarantee',
    'category_conflict':'conflict','invalid_radius':'invalid_range','invalid_price_level':'invalid_range',
    'unsupported_limit_operator':'invalid_range','unsupported_distance_expression':'invalid_range',
    'unsupported_price_expression':'invalid_range','unrecognized_explicit_requirement':'ambiguous_preference',
    'unrecognized_exclusion':'unsupported_constraint',
}


def issue_message(issues):
    codes=[]
    for item in issues:
        code=item['code'] if isinstance(item,dict) else item
        code=LEGACY_CODES.get(code,'unsupported_constraint' if code.startswith('negated_soft_preference:') else code)
        if code not in codes:codes.append(code)
    if len(codes)>1:codes=[c for c in codes if c!='ambiguous_preference']
    return '\n'.join(ISSUE_TEXT.get(code,ISSUE_TEXT['unsupported_constraint']) for code in codes[:3])
