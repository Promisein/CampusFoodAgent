"""Check configuration without a call; --live explicitly performs one API request."""
import argparse
import json

from app.rag.generation import AnswerService
from app.rag.settings import load_settings


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='Perform one billable synthetic DeepSeek smoke request')
    args=parser.parse_args(argv)
    try:settings=load_settings()
    except (ValueError,OSError):
        print(json.dumps({'configured':False,'reason':'invalid_configuration'}));return 1
    if not args.live:
        print(json.dumps(settings.public_status(),ensure_ascii=False,indent=2));return 0
    from app.evaluation.rag_study import make_example
    request,response,reviews=make_example()
    answer=AnswerService(settings).generate(request,response,reviews)
    print(json.dumps({'mode':answer['mode'],'status':answer['status'],'reason':answer['reason'],
                      'model':answer['model'],'usage':answer['usage'],'citations':len(answer['citations'])},ensure_ascii=False,indent=2))
    return 0 if answer['mode']=='deepseek_plan' else 1


if __name__=='__main__':raise SystemExit(main())
