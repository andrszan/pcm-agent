import {
  Bubble,
  BubbleContent,
  BubbleGroup,
} from "@/registry/bases/base/ui/bubble"
import { Message, MessageContent } from "@/registry/bases/base/ui/message"

export function MessageDefault() {
  return (
    <div className="flex w-full max-w-md min-w-0 flex-col gap-10">
      <Message align="end">
        <MessageContent>
          <Bubble>
            <BubbleContent>Deploying to prod real quick.</BubbleContent>
          </Bubble>
        </MessageContent>
      </Message>
      <Message>
        <MessageContent>
          <Bubble variant="muted">
            <BubbleContent>It&apos;s 4:55 PM. On a Friday.</BubbleContent>
          </Bubble>
        </MessageContent>
      </Message>
      <Message align="end">
        <MessageContent>
          <Bubble>
            <BubbleContent>It&apos;s a one-line change.</BubbleContent>
          </Bubble>
        </MessageContent>
      </Message>
      <Message>
        <MessageContent>
          <BubbleGroup>
            <Bubble variant="muted">
              <BubbleContent>
                It&apos;s always a one-line change 😭. Make sure to run the
                tests this time.
              </BubbleContent>
            </Bubble>
            <Bubble variant="muted">
              <BubbleContent>Alright, go for it.</BubbleContent>
            </Bubble>
          </BubbleGroup>
        </MessageContent>
      </Message>
    </div>
  )
}
