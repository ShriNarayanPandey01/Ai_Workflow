import { createContext, useContext, useMemo, type ReactNode } from "react"
import { useParams } from "react-router-dom"

type ProjectContextValue = {
  projectId: string | undefined
}

const ProjectContext = createContext<ProjectContextValue>({ projectId: undefined })

export const ProjectProvider = ({ children }: { children: ReactNode }) => {
  const { projectId } = useParams()
  const value = useMemo(() => ({ projectId }), [projectId])
  return <ProjectContext.Provider value={value}>{children}</ProjectContext.Provider>
}

export const useProjectId = () => {
  return useContext(ProjectContext).projectId
}
